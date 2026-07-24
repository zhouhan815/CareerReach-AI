from __future__ import annotations

import argparse
import json
from pathlib import Path

from boss_agent_cli.cache.store import CacheStore
from boss_agent_cli.opportunity.constraints import assess_fit_constraints
from boss_agent_cli.opportunity.filters import (
	detect_actual_location_mismatch,
	detect_anonymous_or_headhunter,
	detect_company_too_large,
	detect_internship_like,
)
from boss_agent_cli.opportunity.pipeline import analyze_candidate
from boss_agent_cli.resume.models import resume_to_text
from boss_agent_cli.resume.store import ResumeStore


USER_CONFIRMED_CLOSED = {
	"上海九点智投投资顾问": "用户已在 BOSS 详情页确认职位关闭",
	"新舟教育": "用户已在 BOSS 详情页确认职位关闭",
}


def main() -> None:
	parser = argparse.ArgumentParser()
	parser.add_argument("--data-dir", required=True)
	parser.add_argument("--output", required=True)
	parser.add_argument("--resume", default="ai_pm_intern")
	args = parser.parse_args()

	data_dir = Path(args.data_dir)
	resume = ResumeStore(data_dir / "resumes").get(args.resume)
	if resume is None:
		raise RuntimeError(f"resume not found: {args.resume}")
	resume_text = resume_to_text(resume)

	with CacheStore(data_dir / "cache" / "boss_agent.db") as cache:
		items = cache.list_opportunity_candidates(limit=1000)

	latest_by_job: dict[str, dict] = {}
	for item in items:
		job_id = str(item.get("job_id") or "").strip()
		if not job_id:
			continue
		current = latest_by_job.get(job_id)
		quality = (bool(item.get("description")), len(str(item.get("description") or "")), float(item.get("updated_at") or 0))
		current_quality = (
			bool(current and current.get("description")),
			len(str(current.get("description") or "")) if current else 0,
			float(current.get("updated_at") or 0) if current else 0,
		)
		if current is None or quality > current_quality:
			latest_by_job[job_id] = item

	results = []
	for item in latest_by_job.values():
		analyzed = analyze_candidate(item, resume_text, include_web_research=False)
		reasons: list[str] = []
		company = str(analyzed.get("company") or "")
		if company in USER_CONFIRMED_CLOSED:
			reasons.append(USER_CONFIRMED_CLOSED[company])
		for detector in (detect_internship_like, detect_company_too_large, detect_anonymous_or_headhunter, detect_actual_location_mismatch):
			excluded, detector_reasons = detector(analyzed)
			if excluded:
				reasons.extend(detector_reasons)
		constraints = assess_fit_constraints(analyzed, resume_text)
		reasons.extend(constraints.hard_exclusion_reasons)
		match_score = int(analyzed.get("resume_match_score") or 0)
		if match_score < 70:
			reasons.append(f"简历匹配度 {match_score}/100，低于候选池最低门槛 70 分")
		analyzed["review_status"] = "excluded" if reasons else "candidate"
		analyzed["review_reason"] = "；".join(dict.fromkeys(reasons))
		results.append(analyzed)

	results.sort(
		key=lambda item: (
			item["review_status"] == "candidate",
			int(item.get("resume_match_score") or 0),
			int(item.get("internship_acceptance_score") or 0),
		),
		reverse=True,
	)
	Path(args.output).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
	print(json.dumps({
		"count": len(results),
		"candidates": sum(item["review_status"] == "candidate" for item in results),
		"excluded": sum(item["review_status"] == "excluded" for item in results),
	}, ensure_ascii=False))


if __name__ == "__main__":
	main()
