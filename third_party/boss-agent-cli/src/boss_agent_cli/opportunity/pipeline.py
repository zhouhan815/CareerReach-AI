from __future__ import annotations

import hashlib
import time
from typing import Any

from boss_agent_cli.api.models import JobItem
from boss_agent_cli.cache.store import CacheStore
from boss_agent_cli.opportunity.constraints import assess_fit_constraints
from boss_agent_cli.opportunity.drafts import build_greeting_message
from boss_agent_cli.opportunity.filters import (
	detect_actual_location_mismatch,
	detect_anonymous_or_headhunter,
	detect_company_too_large,
	detect_internship_like,
	detect_job_closed,
	normalize_text,
	resolve_work_arrangement,
)
from boss_agent_cli.opportunity.models import OpportunityCandidate
from boss_agent_cli.opportunity.research import infer_company_business, summarize_job_requirement, web_research_company
from boss_agent_cli.opportunity.scoring import score_opportunity
from boss_agent_cli.api.client import AccountRiskError
from boss_agent_cli.safety.risk_lock import AccountRiskLocked
from boss_agent_cli.search_filters import SearchPipelinePlatformError


_TERMINAL_DETAIL_ERROR_CODES = {
	"ACCOUNT_RISK",
	"AUTH_EXPIRED",
	"AUTH_REQUIRED",
	"PLATFORM_VERIFICATION_REQUIRED",
	"RATE_LIMITED",
	"TOKEN_REFRESH_FAILED",
}


def _unwrap_platform_data(platform: Any, response: dict[str, Any]) -> dict[str, Any]:
	data = platform.unwrap_data(response) if hasattr(platform, "unwrap_data") else response.get("zpData")
	return data if isinstance(data, dict) else {}


def _candidate_id(company: str, title: str, job_id: str, city: str) -> str:
	raw = f"{company}|{title}|{job_id}|{city}".encode("utf-8")
	return hashlib.sha1(raw).hexdigest()[:16]


def _safe_list(value: Any) -> list[str]:
	if isinstance(value, list):
		return [str(item) for item in value if str(item).strip()]
	if value:
		return [str(value)]
	return []


def _base_from_raw(raw_item: dict[str, Any], *, run_id: str, query: str, city: str) -> dict[str, Any]:
	item = JobItem.from_api(raw_item)
	location = item.city
	if item.district:
		location = f"{item.city}-{item.district}"
	return {
		"candidate_id": _candidate_id(item.company, item.title, item.job_id, item.city or city),
		"run_id": run_id,
		"status": "pending",
		"query": query,
		"city": item.city or city,
		"title": item.title,
		"company": item.company,
		"salary": item.salary,
		"location": location,
		"company_scale": item.scale,
		"company_stage": item.stage,
		"industry": item.industry,
		"experience": item.experience,
		"education": item.education,
		"security_id": item.security_id,
		"job_id": item.job_id,
		"lid": normalize_text(raw_item.get("lid")),
		"boss_name": item.boss_name,
		"boss_title": item.boss_title,
		"description": "",
		"skills": item.skills,
		"welfare": item.welfare,
		"weekly_days": normalize_text(raw_item.get("daysPerWeekDesc")) or "待沟通",
		"internship_duration": normalize_text(raw_item.get("leastMonthDesc")) or "待沟通",
		"payload": {"raw": raw_item},
	}


def _merge_job_card(candidate: dict[str, Any], card: dict[str, Any]) -> dict[str, Any]:
	if not card:
		return candidate
	candidate = dict(candidate)
	candidate["job_id"] = card.get("encryptJobId") or candidate.get("job_id", "")
	candidate["title"] = card.get("jobName") or candidate.get("title", "")
	candidate["company"] = card.get("brandName") or candidate.get("company", "")
	candidate["salary"] = card.get("salaryDesc") or candidate.get("salary", "")
	candidate["city"] = card.get("cityName") or candidate.get("city", "")
	address = card.get("address") or ""
	candidate["location"] = address or candidate.get("location", "")
	candidate["experience"] = card.get("experienceName") or candidate.get("experience", "")
	candidate["education"] = card.get("degreeName") or candidate.get("education", "")
	candidate["description"] = card.get("postDescription") or candidate.get("description", "")
	candidate["skills"] = _safe_list(card.get("jobLabels")) or candidate.get("skills", [])
	candidate["boss_name"] = card.get("bossName") or candidate.get("boss_name", "")
	candidate["boss_title"] = card.get("bossTitle") or candidate.get("boss_title", "")
	candidate["job_status"] = card.get("jobStatus") or card.get("jobValidStatus") or candidate.get("job_status", "")
	candidate["status_desc"] = card.get("statusDesc") or candidate.get("status_desc", "")
	weekly_days, internship_duration = resolve_work_arrangement(
		card.get("daysPerWeekDesc"),
		card.get("leastMonthDesc"),
		card.get("postDescription"),
		candidate.get("weekly_days"),
		candidate.get("internship_duration"),
	)
	candidate["weekly_days"] = weekly_days
	candidate["internship_duration"] = internship_duration
	candidate["candidate_id"] = _candidate_id(
		normalize_text(candidate.get("company")),
		normalize_text(candidate.get("title")),
		normalize_text(candidate.get("job_id")),
		normalize_text(candidate.get("city")),
	)
	payload = dict(candidate.get("payload") or {})
	payload["job_card"] = card
	candidate["payload"] = payload
	return candidate


def _detail_data_to_job_card(data: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
	job_info = data.get("jobInfo", {})
	if not isinstance(job_info, dict) or not job_info:
		return {}
	boss_info = data.get("bossInfo", {})
	if not isinstance(boss_info, dict):
		boss_info = {}
	brand_info = data.get("brandComInfo", {})
	if not isinstance(brand_info, dict):
		brand_info = {}
	return {
		"encryptJobId": job_info.get("encryptJobId") or candidate.get("job_id", ""),
		"jobName": job_info.get("jobName") or candidate.get("title", ""),
		"brandName": brand_info.get("brandName") or candidate.get("company", ""),
		"salaryDesc": job_info.get("salaryDesc") or candidate.get("salary", ""),
		"cityName": job_info.get("cityName") or candidate.get("city", ""),
		"address": job_info.get("address") or candidate.get("location", ""),
		"experienceName": job_info.get("experienceName") or candidate.get("experience", ""),
		"degreeName": job_info.get("degreeName") or candidate.get("education", ""),
		"postDescription": data.get("jobDetail") or job_info.get("postDescription", ""),
		"jobLabels": job_info.get("jobLabels", []) or job_info.get("skills", []) or candidate.get("skills", []),
		"bossName": boss_info.get("name") or boss_info.get("bossName") or candidate.get("boss_name", ""),
		"bossTitle": boss_info.get("title") or boss_info.get("bossTitle") or candidate.get("boss_title", ""),
		"daysPerWeekDesc": job_info.get("daysPerWeekDesc") or candidate.get("weekly_days", ""),
		"leastMonthDesc": job_info.get("leastMonthDesc") or candidate.get("internship_duration", ""),
		"jobStatus": job_info.get("jobStatus") or job_info.get("status"),
		"jobValidStatus": job_info.get("jobValidStatus"),
		"statusDesc": job_info.get("statusDesc") or data.get("statusDesc"),
	}


def _fetch_detail_card(platform: Any, candidate: dict[str, Any]) -> dict[str, Any]:
	job_id = normalize_text(candidate.get("job_id"))
	if job_id:
		try:
			raw_detail = platform.job_detail(job_id)
			if not platform.is_success(raw_detail):
				code, message = platform.parse_error(raw_detail)
				raise SearchPipelinePlatformError(code, message or "job_detail failed")
			data = _unwrap_platform_data(platform, raw_detail)
			card = _detail_data_to_job_card(data, candidate)
			if card:
				return card
		except (AttributeError, NotImplementedError):
			pass
		except (AccountRiskError, AccountRiskLocked, SearchPipelinePlatformError):
			raise
		except Exception:
			return {}

	security_id = normalize_text(candidate.get("security_id"))
	lid = normalize_text(candidate.get("lid"))
	if not security_id:
		return {}
	raw = platform.job_card(security_id, lid)
	if not platform.is_success(raw):
		code, message = platform.parse_error(raw)
		raise SearchPipelinePlatformError(code, message or "job_card failed")
	data = _unwrap_platform_data(platform, raw)
	card = data.get("jobCard", {})
	return card if isinstance(card, dict) else {}


def _resolve_candidate_work_arrangement(candidate: dict[str, Any]) -> tuple[str, str]:
	payload = candidate.get("payload") or {}
	if not isinstance(payload, dict):
		payload = {}
	raw = payload.get("raw") or {}
	if not isinstance(raw, dict):
		raw = {}
	card = payload.get("job_card") or {}
	if not isinstance(card, dict):
		card = {}
	return resolve_work_arrangement(
		raw.get("daysPerWeekDesc"),
		raw.get("leastMonthDesc"),
		card.get("daysPerWeekDesc"),
		card.get("leastMonthDesc"),
		candidate.get("description"),
	)


def analyze_candidate(candidate: dict[str, Any], resume_text: str, *, include_web_research: bool = False) -> dict[str, Any]:
	candidate = dict(candidate)
	company_business = infer_company_business(candidate)
	web_snippet = ""
	if include_web_research and candidate.get("company"):
		web_snippet = web_research_company(str(candidate["company"]))
		if web_snippet and company_business == "业务方向待进一步确认":
			company_business = web_snippet[:80]
	candidate["company_business"] = company_business
	candidate["job_requirement_judgment"] = summarize_job_requirement(candidate)
	if web_snippet:
		payload = dict(candidate.get("payload") or {})
		payload["web_research_snippet"] = web_snippet
		candidate["payload"] = payload
	weekly_days, internship_duration = _resolve_candidate_work_arrangement(candidate)
	candidate["weekly_days"] = weekly_days
	candidate["internship_duration"] = internship_duration

	scores = score_opportunity(candidate, resume_text)
	candidate.update(scores.to_dict())
	candidate["greeting_message"] = build_greeting_message(candidate)
	return candidate


def collect_opportunities(
	platform: Any,
	cache: CacheStore,
	logger: Any,
	*,
	resume_text: str,
	query: str,
	cities: list[str],
	pages: int = 1,
	limit: int = 10,
	min_match: int = 70,
	min_acceptance: int = 58,
	include_web_research: bool = False,
) -> dict[str, Any]:
	"""Search formal roles, analyze them against the resume, and store results."""
	run_id = time.strftime("opp-%Y%m%d-%H%M%S")
	collected: list[dict[str, Any]] = []
	city_count = max(1, len(cities))
	base_quota = max(0, limit) // city_count
	extra_quota = max(0, limit) % city_count
	city_targets = {
		city: base_quota + (1 if idx < extra_quota else 0)
		for idx, city in enumerate(cities)
	}
	pending_by_city = {city: 0 for city in cities}
	stats = {
		"run_id": run_id,
		"jobs_seen": 0,
		"excluded_internship": 0,
		"excluded_company_scale": 0,
		"search_failures": 0,
		"detail_failures": 0,
		"pending": 0,
		"pending_by_city": pending_by_city,
		"city_targets": city_targets,
		"filtered": 0,
		"duplicates_seen": 0,
	}

	for city in cities:
		city_target = city_targets.get(city, limit)
		if city_target <= 0:
			continue
		for page in range(1, pages + 1):
			if pending_by_city[city] >= city_target:
				break
			logger.info(f"opportunity 搜索 {city} 第 {page} 页")
			try:
				raw = platform.search_jobs(query, city=city, page=page)
			except (AccountRiskError, AccountRiskLocked) as exc:
				raise SearchPipelinePlatformError("ACCOUNT_RISK", str(exc)) from exc
			except Exception as exc:
				stats["search_failures"] += 1
				logger.warning(f"opportunity 搜索失败 {city} 第 {page} 页: {exc}")
				break
			if not platform.is_success(raw):
				code, message = platform.parse_error(raw)
				raise SearchPipelinePlatformError(code, message or "职位搜索失败")
			data = _unwrap_platform_data(platform, raw)
			job_list = data.get("jobList", [])
			if not isinstance(job_list, list) or not job_list:
				break
			stats["jobs_seen"] += len(job_list)
			for raw_item in job_list:
				base = _base_from_raw(raw_item, run_id=run_id, query=query, city=city)
				existing_candidate = cache.get_opportunity_candidate(str(base.get("candidate_id") or ""))
				is_existing_candidate = existing_candidate is not None
				if is_existing_candidate:
					stats["duplicates_seen"] += 1
				internship_like, reasons = detect_internship_like(base)
				if internship_like:
					base["status"] = "excluded"
					base["excluded_reason"] = "；".join(reasons)
					candidate = OpportunityCandidate.from_dict(base)
					cache.upsert_opportunity_candidate(candidate.to_dict())
					collected.append(candidate.to_dict())
					stats["excluded_internship"] += 1
					continue
				company_too_large, reasons = detect_company_too_large(base)
				if company_too_large:
					base["status"] = "excluded"
					base["excluded_reason"] = "；".join(reasons)
					candidate = OpportunityCandidate.from_dict(base)
					cache.upsert_opportunity_candidate(candidate.to_dict())
					collected.append(candidate.to_dict())
					stats["excluded_company_scale"] += 1
					continue
				anonymous, reasons = detect_anonymous_or_headhunter(base)
				if anonymous:
					base["status"] = "excluded"
					base["excluded_reason"] = "；".join(reasons)
					candidate = OpportunityCandidate.from_dict(base)
					cache.upsert_opportunity_candidate(candidate.to_dict())
					collected.append(candidate.to_dict())
					stats["filtered"] += 1
					continue

				try:
					card = _fetch_detail_card(platform, base)
					base = _merge_job_card(base, card)
				except (AccountRiskError, AccountRiskLocked) as exc:
					raise SearchPipelinePlatformError("ACCOUNT_RISK", str(exc)) from exc
				except SearchPipelinePlatformError as exc:
					if exc.code in _TERMINAL_DETAIL_ERROR_CODES:
						raise
					stats["detail_failures"] += 1
					logger.warning(f"opportunity 璇︽儏澶辫触 {base.get('company')} {base.get('title')}: {exc}")
				except Exception as exc:
					stats["detail_failures"] += 1
					logger.warning(f"opportunity 详情失败 {base.get('company')} {base.get('title')}: {exc}")
				analyzed = analyze_candidate(base, resume_text, include_web_research=include_web_research)
				closed, closed_reasons = detect_job_closed(analyzed)
				location_mismatch, location_reasons = detect_actual_location_mismatch(analyzed)
				constraints = assess_fit_constraints(analyzed, resume_text)
				if closed or location_mismatch or constraints.hard_exclusion_reasons:
					analyzed["status"] = "excluded"
					analyzed["excluded_reason"] = "；".join([
						*closed_reasons, *location_reasons, *constraints.hard_exclusion_reasons,
					])
					stats["filtered"] += 1
				elif (
					int(analyzed.get("resume_match_score") or 0) >= min_match
					and int(analyzed.get("internship_acceptance_score") or 0) >= min_acceptance
				):
					analyzed["status"] = "pending"
					if not is_existing_candidate:
						stats["pending"] += 1
						pending_by_city[city] += 1
				else:
					analyzed["status"] = "filtered"
					stats["filtered"] += 1
				candidate = OpportunityCandidate.from_dict(analyzed)
				cache.upsert_opportunity_candidate(candidate.to_dict())
				collected.append(candidate.to_dict())
				if pending_by_city[city] >= city_target:
					break
			if not data.get("hasMore", False):
				break

	return {
		"run_id": run_id,
		"items": collected,
		"stats": stats,
	}
