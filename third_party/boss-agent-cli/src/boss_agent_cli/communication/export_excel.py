from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from boss_agent_cli.communication.models import OpportunitySeed
from boss_agent_cli.communication.outreach_playbook import CAREERREACH_DRAFT_STYLE

COMMUNICATION_COLUMNS = [
	"communication_goal",
	"recommended_action",
	"draft_steady",
	"draft_proactive",
	"draft_short",
	"follow_up_plan",
	"communication_confidence",
	"communication_risk_flags",
	"communication_evidence_ids",
]


class CommunicationExcelDependencyError(RuntimeError):
	"""Raised when openpyxl is unavailable."""


def load_rows_from_workbook(path: Path, *, sheet_name: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
	try:
		import openpyxl
	except ModuleNotFoundError as exc:
		raise CommunicationExcelDependencyError("openpyxl is required for communication export") from exc

	workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
	resolved_sheet = sheet_name if sheet_name and sheet_name in workbook.sheetnames else workbook.sheetnames[0]
	sheet = workbook[resolved_sheet]
	header_row = next(sheet.iter_rows(min_row=1, max_row=1, values_only=True))
	headers = [str(value).strip() if value is not None else "" for value in header_row]
	rows: list[dict[str, Any]] = []
	for row_number, values in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
		if not any(_text(value) for value in values):
			continue
		item = {headers[index]: values[index] if index < len(values) else "" for index in range(len(headers)) if headers[index]}
		item["_source_row"] = row_number
		item["_source_sheet"] = resolved_sheet
		rows.append(item)
		if limit is not None and len(rows) >= limit:
			break
	return rows


def export_communication_workbook(
	rows: list[dict[str, Any]],
	output_path: Path,
	plan_factory: Callable[[OpportunitySeed], dict[str, Any]],
	*,
	input_path: Path | None = None,
	sheet_name: str | None = None,
) -> dict[str, Any]:
	try:
		import openpyxl
	except ModuleNotFoundError as exc:
		raise CommunicationExcelDependencyError("openpyxl is required for communication export") from exc

	output_path.parent.mkdir(parents=True, exist_ok=True)
	if input_path is not None and input_path.exists():
		workbook = openpyxl.load_workbook(input_path)
		resolved_sheet = sheet_name if sheet_name and sheet_name in workbook.sheetnames else None
		if resolved_sheet is None and rows:
			resolved_sheet = str(rows[0].get("_source_sheet") or workbook.sheetnames[0])
		if resolved_sheet is None:
			resolved_sheet = workbook.sheetnames[0]
		sheet = workbook[resolved_sheet]
		headers = [str(cell.value or "").strip() for cell in sheet[1]]
		for column in COMMUNICATION_COLUMNS:
			if column not in headers:
				headers.append(column)
				sheet.cell(row=1, column=len(headers)).value = column
	else:
		workbook = openpyxl.Workbook()
		sheet = workbook.active
		sheet.title = "候选公司总表"
		original_headers = [key for key in rows[0].keys() if not key.startswith("_")] if rows else []
		headers = [*original_headers, *COMMUNICATION_COLUMNS]
		sheet.append(headers)

	results: list[dict[str, Any]] = []
	for row in rows:
		seed = seed_from_row(row)
		result = plan_factory(seed)
		plan = result["plan"]
		drafts = {item.get("style"): item for item in plan.get("drafts", [])}
		communication_values = {
			"communication_goal": plan.get("communication_goal", ""),
			"recommended_action": plan.get("recommended_action", ""),
			"draft_steady": _draft_message(drafts, CAREERREACH_DRAFT_STYLE) or _first_draft_message(plan.get("drafts", [])),
			"draft_proactive": _draft_message(drafts, "主动版"),
			"draft_short": _draft_message(drafts, "简洁版"),
			"follow_up_plan": plan.get("follow_up_plan", ""),
			"communication_confidence": plan.get("confidence", ""),
			"communication_risk_flags": "；".join(plan.get("risk_flags", [])),
			"communication_evidence_ids": "；".join(plan.get("evidence_ids", [])),
		}
		source_row = int(row.get("_source_row") or (sheet.max_row + 1))
		if source_row > sheet.max_row:
			for index, header in enumerate(headers, start=1):
				if header not in COMMUNICATION_COLUMNS:
					sheet.cell(row=source_row, column=index).value = row.get(header, "")
		for column in COMMUNICATION_COLUMNS:
			sheet.cell(row=source_row, column=headers.index(column) + 1).value = communication_values[column]
		results.append({"source_row": row.get("_source_row"), "company": seed.company, "job_title": seed.job_title, "plan": plan})

	for column in sheet.columns:
		header = str(column[0].value or "")
		width = 16
		if header in {"draft_steady", "draft_proactive", "draft_short", "follow_up_plan"}:
			width = 48
		sheet.column_dimensions[column[0].column_letter].width = width
	workbook.save(output_path)
	return {"output": str(output_path), "count": len(rows), "items": results}


def seed_from_row(row: dict[str, Any]) -> OpportunitySeed:
	company = _first(row, ("公司名称", "公司名", "公司", "company", "brandName"))
	job_title = _first(row, ("岗位名称", "职位名称", "title", "jobName"))
	job_id = _first(row, ("job_id", "jobId", "encryptJobId"))
	security_id = _first(row, ("security_id", "securityId"))
	facts = {
		"company_business": _first(row, ("公司主要业务", "company_business", "business")),
		"company_size": _first(row, ("公司规模", "规模", "company_size")),
		"location": _first(row, ("工作地点", "地点", "location", "address")),
		"salary": _first(row, ("薪资", "salary")),
		"internship_days": _first(row, ("一周实习几天", "实习天数", "internship_days")),
		"internship_duration": _first(row, ("实习时长", "internship_duration")),
		"resume_match_score": _first(row, ("简历匹配度", "match_score", "resume_match_score")),
		"internship_acceptance": _first(row, ("实习接收可能性", "internship_acceptance")),
		"recommendation_level": _first(row, ("推荐等级", "recommendation_level")),
		"status": _first(row, ("状态", "status")),
		"job_requirement_judgment": _first(row, ("岗位需求判断", "job_requirement_judgment", "description")),
		"match_reasons": _first(row, ("匹配理由", "match_reasons")),
		"risk_to_confirm": _first(row, ("风险/待确认", "risk_to_confirm")),
		"existing_greeting": _first(row, ("生成的打招呼话术", "greeting", "draft_greeting")),
		"job_url": _first(row, ("岗位网址", "job_url", "url")),
		"skills": _first(row, ("skills", "技能")),
	}
	context_keys = (
		"company_business",
		"company_size",
		"location",
		"salary",
		"internship_days",
		"internship_duration",
		"job_requirement_judgment",
		"match_reasons",
		"risk_to_confirm",
		"existing_greeting",
	)
	context_labels = {
		"company_business": "company business",
		"company_size": "company size",
		"location": "location",
		"salary": "salary",
		"internship_days": "internship days",
		"internship_duration": "internship duration",
		"job_requirement_judgment": "job requirement",
		"match_reasons": "match reasons",
		"risk_to_confirm": "risk to confirm",
		"existing_greeting": "existing greeting",
	}
	extra_context = [f"{context_labels[key]}: {facts[key]}" for key in context_keys if facts.get(key)]
	return OpportunitySeed(
		company=company,
		job_title=job_title,
		job_id=job_id,
		security_id=security_id,
		goal="initial_outreach",
		extra_context=extra_context,
		facts={key: value for key, value in facts.items() if value},
	)


def _draft_message(drafts: dict[str, dict[str, Any]], style: str) -> str:
	item = drafts.get(style) or {}
	return str(item.get("message") or "")


def _first_draft_message(drafts: list[dict[str, Any]]) -> str:
	for item in drafts:
		message = str(item.get("message") or "")
		if message:
			return message
	return ""


def _first(row: dict[str, Any], keys: tuple[str, ...]) -> str:
	for key in keys:
		value = row.get(key)
		if _text(value):
			return _text(value)
	return ""


def _text(value: Any) -> str:
	if value is None:
		return ""
	return str(value).strip()
