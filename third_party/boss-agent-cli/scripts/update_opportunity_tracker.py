from __future__ import annotations

import argparse
import json
import sys
import time
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from boss_agent_cli.api.client import BossClient
from boss_agent_cli.auth.manager import AuthManager
from boss_agent_cli.cache.store import CacheStore
from boss_agent_cli.opportunity.constraints import assess_fit_constraints
from boss_agent_cli.opportunity.export_excel import export_opportunities_xlsx
from boss_agent_cli.opportunity.filters import (
	detect_actual_location_mismatch,
	detect_anonymous_or_headhunter,
	detect_company_too_large,
	detect_internship_like,
	detect_job_closed,
)
from boss_agent_cli.opportunity.models import OpportunityCandidate
from boss_agent_cli.opportunity.pipeline import (
	_base_from_raw,
	_detail_data_to_job_card,
	_merge_job_card,
	analyze_candidate,
)
from boss_agent_cli.output import Logger
from boss_agent_cli.platforms.zhipin import BossPlatform
from boss_agent_cli.resume.models import resume_to_text
from boss_agent_cli.resume.store import ResumeStore
from boss_agent_cli.search_filters import resolve_search_code_params


DEFAULT_SCALES = "0-20人,20-99人,100-499人,500-999人"
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def _parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="Realtime BOSS opportunity tracker updater")
	parser.add_argument("--data-dir", required=True)
	parser.add_argument("--output", required=True)
	parser.add_argument("--query", default="AI产品经理")
	parser.add_argument("--queries", default=None, help="Comma-separated query variants; overrides --query")
	parser.add_argument("--cities", default="上海,深圳")
	parser.add_argument("--resume", default="ai_pm_intern")
	parser.add_argument("--pages", type=int, default=5)
	parser.add_argument("--limit", type=int, default=20)
	parser.add_argument("--min-match", type=int, default=70)
	parser.add_argument("--min-acceptance", type=int, default=58)
	parser.add_argument("--scales", default=DEFAULT_SCALES)
	parser.add_argument("--log-level", default="info")
	return parser.parse_args()


def _inline_text(cell: ET.Element) -> str:
	text = cell.find(f"{NS}is/{NS}t")
	return text.text if text is not None and text.text is not None else ""


def _read_existing_statuses(path: Path) -> dict[str, str]:
	if not path.exists():
		return {}
	try:
		with zipfile.ZipFile(path) as workbook:
			root = ET.fromstring(workbook.read("xl/worksheets/sheet1.xml"))
	except Exception:
		return {}
	rows = []
	for row in root.findall(f".//{NS}row"):
		rows.append([_inline_text(cell) for cell in row.findall(f"{NS}c")])
	if not rows:
		return {}
	header = rows[0]
	try:
		job_id_index = header.index("job_id")
		status_index = header.index("状态")
	except ValueError:
		return {}
	statuses: dict[str, str] = {}
	for row in rows[1:]:
		if len(row) <= max(job_id_index, status_index):
			continue
		job_id = row[job_id_index].strip()
		status = row[status_index].strip()
		if job_id and status:
			statuses[job_id] = status
	return statuses


def _unwrap(platform: BossPlatform, response: dict[str, Any]) -> dict[str, Any]:
	data = platform.unwrap_data(response)
	return data if isinstance(data, dict) else {}


def _search_page(
	platform: BossPlatform,
	query: str,
	city: str,
	page: int,
	raw_params: dict[str, str],
) -> tuple[list[dict[str, Any]], bool]:
	response = platform.search_jobs(query, city=city, page=page, raw_params=raw_params)
	if not platform.is_success(response):
		code, message = platform.parse_error(response)
		raise RuntimeError(f"search failed: {city} page={page} {code} {message}")
	data = _unwrap(platform, response)
	job_list = data.get("jobList", [])
	return (job_list if isinstance(job_list, list) else []), bool(data.get("hasMore"))


def _attach_detail(platform: BossPlatform, candidate: dict[str, Any]) -> tuple[dict[str, Any], str]:
	job_id = str(candidate.get("job_id") or "").strip()
	detail_error = ""
	if job_id:
		response = platform.job_detail(job_id)
		if platform.is_success(response):
			card = _detail_data_to_job_card(_unwrap(platform, response), candidate)
			if card:
				return _merge_job_card(candidate, card), ""
		else:
			code, message = platform.parse_error(response)
			detail_error = f"{code}: {message}"
	else:
		detail_error = "missing job_id"

	# The list-detail endpoint can reject a fresh session even when the visible
	# job-card endpoint is available in the same logged-in browser. Fall back to
	# the card route before treating the JD as unavailable.
	security_id = str(candidate.get("security_id") or "").strip()
	lid = str(candidate.get("lid") or "").strip()
	if not security_id:
		return candidate, detail_error
	card_response = platform.job_card(security_id, lid)
	if not platform.is_success(card_response):
		code, message = platform.parse_error(card_response)
		return candidate, "；".join(part for part in (detail_error, f"{code}: {message}") if part)
	data = _unwrap(platform, card_response)
	card = data.get("jobCard", {}) if isinstance(data, dict) else {}
	return _merge_job_card(candidate, card if isinstance(card, dict) else {}), ""


def _sort_pending(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
	return sorted(
		items,
		key=lambda item: (
			{"A": 3, "B": 2, "C": 1}.get(str(item.get("recommendation_level")), 0),
			int(item.get("resume_match_score") or 0),
			int(item.get("internship_acceptance_score") or 0),
		),
		reverse=True,
	)


def _progress(message: str) -> None:
	print(message, file=sys.stderr, flush=True)


def main() -> None:
	args = _parse_args()
	data_dir = Path(args.data_dir)
	output_path = Path(args.output)
	cities = [city.strip() for city in args.cities.split(",") if city.strip()]
	queries = [query.strip() for query in (args.queries or args.query).split(",") if query.strip()]
	run_id = time.strftime("opp-live-%Y%m%d-%H%M%S")
	logger = Logger(args.log_level)
	existing_statuses = _read_existing_statuses(output_path)

	resume_store = ResumeStore(data_dir / "resumes")
	resume = resume_store.get(args.resume)
	if resume is None:
		raise RuntimeError(f"resume not found: {args.resume}")
	resume_text = resume_to_text(resume)

	raw_params = {} if args.scales.strip().lower() in {"none", "all", "*"} else resolve_search_code_params(scale=args.scales)
	auth = AuthManager(data_dir, logger=logger, platform="zhipin")
	client = BossClient(auth)
	platform = BossPlatform(client)

	pending: list[dict[str, Any]] = []
	base_quota = args.limit // max(1, len(cities))
	extra_quota = args.limit % max(1, len(cities))
	city_targets = {city: base_quota + (1 if index < extra_quota else 0) for index, city in enumerate(cities)}
	pending_by_city = {city: 0 for city in cities}
	filtered: list[dict[str, Any]] = []
	excluded: list[dict[str, Any]] = []
	seen_job_ids: set[str] = set()
	stats: dict[str, Any] = {
		"run_id": run_id,
		"searched_pages": [],
		"seen": 0,
		"pending": 0,
		"exported_active": 0,
		"excluded": 0,
		"filtered": 0,
		"detail_failures": 0,
		"search_failures": [],
		"existing_statuses_preserved": 0,
		"city_targets": city_targets,
		"pending_by_city": pending_by_city,
	}

	try:
		with CacheStore(data_dir / "cache" / "boss_agent.db") as cache:
			for query in queries:
				for city in cities:
					if pending_by_city[city] >= city_targets[city]:
						continue
					for page in range(1, max(1, args.pages) + 1):
						if pending_by_city[city] >= city_targets[city]:
							break
						_progress(f"[tracker] search {city} {query} page {page}")
						try:
							job_list, has_more = _search_page(platform, query, city, page, raw_params)
						except RuntimeError as exc:
							stats["search_failures"].append({"query": query, "city": city, "page": page, "error": str(exc)})
							_progress(f"[tracker] skip failed page: {city} {query} page {page} - {exc}")
							continue
						stats["searched_pages"].append({"query": query, "city": city, "page": page, "count": len(job_list)})
						_progress(f"[tracker] got {len(job_list)} jobs from {city} {query} page {page}")
						if not job_list:
							break
						for raw_item in job_list:
							stats["seen"] += 1
							base = _base_from_raw(raw_item, run_id=run_id, query=query, city=city)
							job_id = str(base.get("job_id") or "")
							if not job_id or job_id in seen_job_ids:
								continue
							seen_job_ids.add(job_id)

							internship_like, internship_reasons = detect_internship_like(base)
							company_too_large, scale_reasons = detect_company_too_large(base)
							anonymous, anonymous_reasons = detect_anonymous_or_headhunter(base)
							if internship_like or company_too_large or anonymous:
								base["status"] = "excluded"
								base["excluded_reason"] = "；".join([*internship_reasons, *scale_reasons, *anonymous_reasons])
								excluded.append(base)
								cache.upsert_opportunity_candidate(OpportunityCandidate.from_dict(base).to_dict())
								continue

							with_detail, detail_error = _attach_detail(platform, base)
							if detail_error:
								stats["detail_failures"] += 1
							internship_like, internship_reasons = detect_internship_like(with_detail)
							company_too_large, scale_reasons = detect_company_too_large(with_detail)
							anonymous, anonymous_reasons = detect_anonymous_or_headhunter(with_detail)
							closed, closed_reasons = detect_job_closed(with_detail, detail_error)
							location_mismatch, location_reasons = detect_actual_location_mismatch(with_detail)
							if internship_like or company_too_large or anonymous or closed or location_mismatch:
								with_detail["status"] = "excluded"
								with_detail["excluded_reason"] = "；".join([
									*internship_reasons, *scale_reasons, *anonymous_reasons, *closed_reasons, *location_reasons,
								])
								excluded.append(with_detail)
								cache.upsert_opportunity_candidate(OpportunityCandidate.from_dict(with_detail).to_dict())
								continue

							analyzed = analyze_candidate(with_detail, resume_text, include_web_research=False)
							constraints = assess_fit_constraints(analyzed, resume_text)
							if constraints.hard_exclusion_reasons:
								analyzed["status"] = "excluded"
								analyzed["excluded_reason"] = "；".join(constraints.hard_exclusion_reasons)
								excluded.append(analyzed)
							elif (
								int(analyzed.get("resume_match_score") or 0) >= args.min_match
								and int(analyzed.get("internship_acceptance_score") or 0) >= args.min_acceptance
							):
								analyzed["status"] = existing_statuses.get(job_id, "pending")
								if analyzed["status"] != "pending":
									stats["existing_statuses_preserved"] += 1
								pending.append(analyzed)
								pending_by_city[city] += 1
								_progress(
									f"[tracker] pending {len(pending)}/{args.limit}: "
									f"{analyzed.get('city')} {analyzed.get('company')} {analyzed.get('title')} "
									f"match={analyzed.get('resume_match_score')} "
									f"accept={analyzed.get('internship_acceptance_score')}"
								)
							else:
								analyzed["status"] = "filtered"
								filtered.append(analyzed)
								stats["filtered"] += 1

							cache.upsert_opportunity_candidate(OpportunityCandidate.from_dict(analyzed).to_dict())
							if pending_by_city[city] >= city_targets[city]:
								break
						if not has_more:
							break
				if len(pending) >= args.limit:
					break
	finally:
		platform.close()

	selected = _sort_pending(pending)[: args.limit]
	stats["pending"] = sum(1 for item in selected if item.get("status") == "pending")
	stats["exported_active"] = len(selected)
	stats["excluded"] = len(excluded)
	export_opportunities_xlsx([*selected, *excluded], output_path)
	print(json.dumps({"ok": True, "output": str(output_path), "stats": stats}, ensure_ascii=False))


if __name__ == "__main__":
	main()
