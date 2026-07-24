from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from boss_agent_cli.opportunity.drafts import build_greeting_message

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

SHEET_CANDIDATES = "候选公司总表"
SHEET_TOP = "高优先级联系名单"
SHEET_EXCLUDED = "已排除岗位"

_COLUMNS = [
	("公司名", "company"),
	("公司主要业务", "company_business"),
	("公司规模", "company_scale"),
	("岗位名称", "title"),
	("岗位需求判断", "job_requirement_judgment"),
	("工作地点", "location"),
	("薪资", "salary"),
	("一周实习几天", "weekly_days"),
	("实习时长", "internship_duration"),
	("简历匹配度", "resume_match_score"),
	("实习接收可能性", "internship_acceptance_score"),
	("推荐等级", "recommendation_level"),
	("状态", "status"),
	("匹配理由", "match_reasons"),
	("风险/待确认", "risk_reasons"),
	("生成的打招呼话术", "greeting_message"),
	("security_id", "security_id"),
	("job_id", "job_id"),
	("岗位网址", "post_url"),
]

_STANDARD_HEADERS = [label for label, _ in _COLUMNS]
_HEADER_WIDTHS = {
	"公司名": 18,
	"公司主要业务": 30,
	"公司规模": 14,
	"岗位名称": 22,
	"岗位需求判断": 50,
	"工作地点": 22,
	"薪资": 14,
	"一周实习几天": 16,
	"实习时长": 16,
	"简历匹配度": 12,
	"实习接收可能性": 14,
	"推荐等级": 10,
	"状态": 12,
	"匹配理由": 38,
	"风险/待确认": 38,
	"生成的打招呼话术": 90,
	"security_id": 24,
	"job_id": 24,
	"岗位网址": 64,
}
_PRESERVED_STATUSES = {"pending", "confirmed", "sent", "rejected", "excluded", "filtered", "failed"}


def _safe_text(value: Any) -> str:
	if value is None:
		return ""
	if isinstance(value, list):
		text = "；".join(str(item) for item in value)
	else:
		text = str(value)
	text = _CONTROL_RE.sub("", text)
	if text.startswith(("=", "+", "-", "@")):
		return "'" + text
	return text


def _post_url(candidate: dict[str, Any]) -> str:
	existing = _safe_text(candidate.get("post_url", "")).strip()
	if existing:
		return existing
	job_id = _safe_text(candidate.get("job_id", "")).strip()
	security_id = _safe_text(candidate.get("security_id", "")).strip()
	lid = _safe_text(candidate.get("lid", "")).strip()
	if not job_id:
		return ""
	query_parts = []
	if security_id:
		query_parts.append(f"securityId={security_id}")
	if lid:
		query_parts.append(f"lid={lid}")
	query = "&".join(query_parts)
	return f"https://www.zhipin.com/job_detail/{job_id}.html" + (f"?{query}" if query else "")


def _candidate_value(candidate: dict[str, Any], key: str) -> str:
	if key == "post_url":
		return _post_url(candidate)
	if key == "greeting_message":
		return build_greeting_message(candidate)
	return _safe_text(candidate.get(key, ""))


def _row_for_candidate(candidate: dict[str, Any]) -> dict[str, str]:
	return {label: _candidate_value(candidate, key) for label, key in _COLUMNS}


def _normalize_key_part(value: Any) -> str:
	return re.sub(r"\s+", "", _safe_text(value).lower())


def _row_key(row: dict[str, Any]) -> str:
	job_id = _safe_text(row.get("job_id", "")).strip()
	if job_id:
		return f"job:{job_id}"
	security_id = _safe_text(row.get("security_id", "")).strip()
	if security_id:
		return f"security:{security_id}"
	company = _normalize_key_part(row.get("公司名", ""))
	title = _normalize_key_part(row.get("岗位名称", ""))
	location = _normalize_key_part(row.get("工作地点", ""))
	if company and title:
		return f"text:{company}|{title}|{location}"
	return ""


def _status_value(row: dict[str, Any]) -> str:
	return _safe_text(row.get("状态", "")).strip().lower()


def _priority_for_existing_row(row: dict[str, Any]) -> int:
	status = _status_value(row)
	status_priority = {
		"sent": 6,
		"confirmed": 5,
		"rejected": 5,
		"excluded": 5,
		"failed": 4,
		"pending": 3,
		"filtered": 2,
	}
	return status_priority.get(status, 1)


def _openpyxl_modules():
	try:
		from openpyxl import Workbook, load_workbook
		from openpyxl.styles import Alignment, Font, PatternFill
	except ImportError as exc:  # pragma: no cover - local package installs include openpyxl.
		raise RuntimeError(
			"opportunity Excel 导出/合并需要 openpyxl>=3.1；请安装 boss-agent-cli[communication] 或 boss-agent-cli[rag]。"
		) from exc
	return Workbook, load_workbook, Alignment, Font, PatternFill


def _read_existing_workbook(path: Path | None) -> tuple[list[dict[str, str]], list[str]]:
	if path is None or not path.exists():
		return [], []
	_, load_workbook, _, _, _ = _openpyxl_modules()
	workbook = load_workbook(path, data_only=False)
	rows_by_key: dict[str, dict[str, str]] = {}
	order: list[str] = []
	extra_headers: list[str] = []
	for sheet_name in (SHEET_CANDIDATES, SHEET_TOP, SHEET_EXCLUDED):
		if sheet_name not in workbook.sheetnames:
			continue
		sheet = workbook[sheet_name]
		headers = [_safe_text(cell.value).strip() for cell in sheet[1]]
		for header in headers:
			if header and header not in _STANDARD_HEADERS and header not in extra_headers:
				extra_headers.append(header)
		for values in sheet.iter_rows(min_row=2, values_only=True):
			if not values or all(_safe_text(value).strip() == "" for value in values):
				continue
			row = {
				header: _safe_text(values[index]).strip()
				for index, header in enumerate(headers)
				if header and index < len(values)
			}
			key = _row_key(row)
			if not key:
				continue
			current = rows_by_key.get(key)
			if current is None:
				rows_by_key[key] = row
				order.append(key)
			elif _priority_for_existing_row(row) > _priority_for_existing_row(current):
				rows_by_key[key] = row
	return [rows_by_key[key] for key in order if key in rows_by_key], extra_headers


def _merge_row(new_row: dict[str, str], existing_row: dict[str, str] | None) -> dict[str, str]:
	if existing_row is None:
		return dict(new_row)
	merged = dict(existing_row)
	existing_status = _status_value(existing_row)
	for label in _STANDARD_HEADERS:
		new_value = _safe_text(new_row.get(label, "")).strip()
		old_value = _safe_text(existing_row.get(label, "")).strip()
		if label == "状态":
			if existing_status in _PRESERVED_STATUSES:
				merged[label] = old_value
			else:
				merged[label] = new_value or old_value
		elif label == "生成的打招呼话术":
			if existing_status == "sent" and old_value:
				merged[label] = old_value
			else:
				merged[label] = new_value or old_value
		elif new_value:
			merged[label] = new_value
		else:
			merged[label] = old_value
	return merged


def _row_score(row: dict[str, str], header: str) -> int:
	value = _safe_text(row.get(header, "")).strip()
	match = re.search(r"\d+", value)
	return int(match.group(0)) if match else 0


def _is_excluded(row: dict[str, str]) -> bool:
	return _status_value(row) in {"excluded", "rejected"}


def _is_top(row: dict[str, str]) -> bool:
	return row.get("推荐等级") == "A" or _row_score(row, "简历匹配度") >= 80


def _collect_rows(
	candidates: list[dict[str, Any]],
	existing_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
	existing_by_key = {_row_key(row): row for row in existing_rows if _row_key(row)}
	existing_order = [_row_key(row) for row in existing_rows if _row_key(row)]
	merged_by_key = dict(existing_by_key)
	new_order: list[str] = []
	for candidate in candidates:
		new_row = _row_for_candidate(candidate)
		key = _row_key(new_row)
		if not key:
			key = f"new:{len(new_order)}"
		merged_by_key[key] = _merge_row(new_row, existing_by_key.get(key))
		if key not in new_order:
			new_order.append(key)
	seen = set(new_order)
	ordered_keys = [*new_order, *[key for key in existing_order if key not in seen]]
	return [merged_by_key[key] for key in ordered_keys if key in merged_by_key]


def _write_sheet(workbook: Any, sheet_name: str, headers: list[str], rows: list[dict[str, str]]) -> None:
	_, _, Alignment, Font, PatternFill = _openpyxl_modules()
	sheet = workbook.create_sheet(sheet_name)
	sheet.append(headers)
	header_fill = PatternFill("solid", fgColor="EAF2F8")
	for cell in sheet[1]:
		cell.font = Font(bold=True)
		cell.fill = header_fill
		cell.alignment = Alignment(wrap_text=True, vertical="top")
	for row in rows:
		sheet.append([_safe_text(row.get(header, "")) for header in headers])
	for row_cells in sheet.iter_rows(min_row=2):
		for cell in row_cells:
			cell.alignment = Alignment(wrap_text=True, vertical="top")
	for index, header in enumerate(headers, start=1):
		column_letter = sheet.cell(row=1, column=index).column_letter
		sheet.column_dimensions[column_letter].width = _HEADER_WIDTHS.get(header, 18)
	sheet.freeze_panes = "A2"


def export_opportunities_xlsx(
	candidates: list[dict[str, Any]],
	output_path: Path,
	*,
	existing_path: Path | None = None,
) -> Path:
	"""Export opportunities while preserving the existing tracking workbook when present.

	If ``output_path`` already exists, it is treated as the base workbook and updated in-place.
	``existing_path`` can be used to merge from one workbook and write to another path.
	"""
	output_path.parent.mkdir(parents=True, exist_ok=True)
	base_path = existing_path or (output_path if output_path.exists() else None)
	existing_rows, extra_headers = _read_existing_workbook(base_path)
	all_rows = _collect_rows(candidates, existing_rows)
	active_rows = [row for row in all_rows if not _is_excluded(row)]
	top_rows = [row for row in active_rows if _is_top(row)]
	excluded_rows = [row for row in all_rows if _is_excluded(row)]
	headers = [*_STANDARD_HEADERS, *extra_headers]

	Workbook, _, _, _, _ = _openpyxl_modules()
	workbook = Workbook()
	default_sheet = workbook.active
	workbook.remove(default_sheet)
	_write_sheet(workbook, SHEET_CANDIDATES, headers, active_rows)
	_write_sheet(workbook, SHEET_TOP, headers, top_rows)
	_write_sheet(workbook, SHEET_EXCLUDED, headers, excluded_rows)
	workbook.save(output_path)
	return output_path
