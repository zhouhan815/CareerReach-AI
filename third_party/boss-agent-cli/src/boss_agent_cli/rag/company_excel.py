from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any

from boss_agent_cli.rag.models import RagChunk

DEFAULT_COMPANY_SHEET = "候选公司总表"


class RagExcelDependencyError(RuntimeError):
	"""Raised when Excel import dependencies are unavailable."""


def load_company_rows_from_xlsx(path: Path, *, sheet_name: str = DEFAULT_COMPANY_SHEET, limit: int | None = None) -> list[dict[str, Any]]:
	try:
		import openpyxl
	except ModuleNotFoundError as exc:
		raise RagExcelDependencyError("openpyxl is required to import company Excel files") from exc

	workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
	if sheet_name not in workbook.sheetnames:
		if DEFAULT_COMPANY_SHEET in workbook.sheetnames:
			sheet_name = DEFAULT_COMPANY_SHEET
		else:
			raise ValueError(f"sheet {sheet_name!r} not found; available: {', '.join(workbook.sheetnames)}")
	sheet = workbook[sheet_name]
	header_row = next(sheet.iter_rows(min_row=1, max_row=1, values_only=True))
	headers = [str(value).strip() if value is not None else "" for value in header_row]
	rows: list[dict[str, Any]] = []
	for row_number, values in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
		if not any(_text(value) for value in values):
			continue
		item = {headers[index]: values[index] if index < len(values) else "" for index in range(len(headers)) if headers[index]}
		item["_source_row"] = row_number
		item["_source_sheet"] = sheet_name
		rows.append(item)
		if limit is not None and len(rows) >= limit:
			break
	return rows


def chunks_from_company_row(row: dict[str, Any], *, source_path: Path, sheet_name: str) -> list[RagChunk]:
	company = _text(row.get("公司名"))
	job_title = _text(row.get("岗位名称"))
	job_id = _text(row.get("job_id"))
	source_row = int(row.get("_source_row") or 0)
	base_id = job_id or _stable_digest(f"{source_path}|{sheet_name}|{source_row}|{company}|{job_title}")
	base_metadata: dict[str, Any] = {
		"source": "excel_opportunity",
		"source_file": str(source_path),
		"source_sheet": sheet_name,
		"source_row": source_row,
		"company": company,
		"job_title": job_title,
		"job_id": job_id,
		"security_id": _text(row.get("security_id")),
		"job_url": _text(row.get("岗位网址")),
		"location": _text(row.get("工作地点")),
		"company_scale": _text(row.get("公司规模")),
		"salary": _text(row.get("薪资")),
		"status": _text(row.get("状态")),
		"recommendation_level": _text(row.get("推荐等级")),
		"resume_match_score": _int_or_text(row.get("简历匹配度")),
		"internship_acceptance_score": _int_or_text(row.get("实习接收可能性")),
		"indexed_at": time.time(),
	}
	chunk_specs = [
		(
			"company_profile",
			"company",
			[
				("公司", company),
				("公司主要业务", row.get("公司主要业务")),
				("公司规模", row.get("公司规模")),
				("工作地点", row.get("工作地点")),
				("岗位名称", job_title),
				("薪资", row.get("薪资")),
				("推荐等级", row.get("推荐等级")),
				("状态", row.get("状态")),
			],
		),
		(
			"job_requirement",
			"job",
			[
				("公司", company),
				("岗位名称", job_title),
				("岗位需求判断", row.get("岗位需求判断")),
				("匹配理由", row.get("匹配理由")),
				("风险/待确认", row.get("风险/待确认")),
				("一周实习几天", row.get("一周实习几天")),
				("实习时长", row.get("实习时长")),
			],
		),
		(
			"outreach_context",
			"message_template",
			[
				("公司", company),
				("岗位名称", job_title),
				("生成的打招呼话术", row.get("生成的打招呼话术")),
			],
		),
	]
	chunks: list[RagChunk] = []
	for chunk_kind, doc_type, pairs in chunk_specs:
		text = _render_pairs(pairs)
		if not text:
			continue
		metadata = dict(base_metadata)
		metadata["doc_type"] = doc_type
		metadata["chunk_kind"] = chunk_kind
		chunks.append(
			RagChunk(
				chunk_id=f"company:{base_id}:{chunk_kind}",
				text=text,
				metadata=metadata,
			)
		)
	return chunks


def _render_pairs(pairs: list[tuple[str, Any]]) -> str:
	lines = [f"{label}: {_text(value)}" for label, value in pairs if _text(value)]
	return "\n".join(lines)


def _text(value: Any) -> str:
	if value is None:
		return ""
	return str(value).strip()


def _int_or_text(value: Any) -> int | str:
	text = _text(value)
	if not text:
		return ""
	try:
		return int(float(text))
	except ValueError:
		return text


def _stable_digest(value: str) -> str:
	return hashlib.sha1(value.encode("utf-8")).hexdigest()[:16]
