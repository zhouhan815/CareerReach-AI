from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any

from boss_agent_cli.rag.models import RagChunk
from boss_agent_cli.resume.models import ResumeData, dict_to_resume
from boss_agent_cli.resume.store import ResumeStore


class ResumeRagImportError(RuntimeError):
	"""Raised when a resume cannot be loaded for RAG indexing."""


def load_resume_for_rag(data_dir: Path, *, resume_name: str | None = None, input_path: Path | None = None) -> ResumeData:
	if input_path is not None:
		try:
			raw = __import__("json").loads(input_path.read_text(encoding="utf-8-sig"))
		except Exception as exc:
			raise ResumeRagImportError(f"Unable to read resume JSON: {input_path}") from exc
		if "version" in raw and "data" in raw and isinstance(raw["data"], dict):
			raw = raw["data"]
		if not isinstance(raw, dict):
			raise ResumeRagImportError("Resume JSON must be an object or a ResumeFile envelope")
		return dict_to_resume(raw)

	if not resume_name:
		raise ResumeRagImportError("Either --name or --input is required")
	resume = ResumeStore(data_dir / "resumes").get(resume_name)
	if resume is None:
		raise ResumeRagImportError(f"Resume {resume_name!r} was not found in the local resume store")
	return resume


def chunks_from_resume(resume: ResumeData, *, source: str = "resume_store") -> list[RagChunk]:
	resume_name = resume.name or "resume"
	indexed_at = time.time()
	base_metadata: dict[str, Any] = {
		"source": source,
		"doc_type": "resume",
		"resume_name": resume_name,
		"resume_title": resume.title,
		"indexed_at": indexed_at,
	}
	chunks: list[RagChunk] = []

	profile_text = _profile_text(resume)
	if profile_text:
		chunks.append(
			RagChunk(
				chunk_id=f"resume:{_safe_id(resume_name)}:profile",
				text=profile_text,
				metadata={**base_metadata, "chunk_kind": "resume_profile"},
			)
		)

	for module_index, module in enumerate(resume.modules, start=1):
		module_lines = _module_lines(module.rows)
		if not module_lines:
			continue
		module_key = module.id or f"module-{module_index}"
		module_text = _render_lines(
			[
				("resume_name", resume_name),
				("resume_title", resume.title),
				("module_title", module.title),
				("module_content", "\n".join(module_lines)),
			]
		)
		chunks.append(
			RagChunk(
				chunk_id=f"resume:{_safe_id(resume_name)}:module:{_safe_id(module_key)}",
				text=module_text,
				metadata={
					**base_metadata,
					"chunk_kind": "resume_module",
					"module_id": module.id,
					"module_title": module.title,
				},
			)
		)
		for row_index, line in enumerate(module_lines, start=1):
			row_text = _render_lines(
				[
					("resume_name", resume_name),
					("resume_title", resume.title),
					("module_title", module.title),
					("experience", line),
				]
			)
			chunks.append(
				RagChunk(
					chunk_id=f"resume:{_safe_id(resume_name)}:row:{_stable_digest(module_key + str(row_index) + line)}",
					text=row_text,
					metadata={
						**base_metadata,
						"chunk_kind": "resume_experience",
						"module_id": module.id,
						"module_title": module.title,
						"row_index": row_index,
					},
				)
			)
	return chunks


def _profile_text(resume: ResumeData) -> str:
	lines: list[tuple[str, Any]] = [
		("resume_name", resume.name),
		("resume_title", resume.title),
	]
	if resume.job_intention is not None and resume.job_intention.items:
		lines.append(("job_intention", "; ".join(f"{item.label}: {item.value}" for item in resume.job_intention.items)))
	return _render_lines(lines)


def _module_lines(rows: list[dict[str, Any]]) -> list[str]:
	lines: list[str] = []
	for row in rows:
		row_type = str(row.get("type") or "")
		if row_type == "tags":
			tags = row.get("tags") or []
			if isinstance(tags, list):
				value = ", ".join(str(item).strip() for item in tags if str(item).strip())
				if value:
					lines.append(value)
			continue
		content = row.get("content") or []
		if isinstance(content, list):
			for item in content:
				text = str(item).strip()
				if text:
					lines.append(text)
		else:
			text = str(content).strip()
			if text:
				lines.append(text)
	return lines


def _render_lines(pairs: list[tuple[str, Any]]) -> str:
	lines = [f"{label}: {str(value).strip()}" for label, value in pairs if str(value or "").strip()]
	return "\n".join(lines)


def _safe_id(value: str) -> str:
	clean = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in value.strip())
	while "--" in clean:
		clean = clean.replace("--", "-")
	return clean.strip("-") or _stable_digest(value)


def _stable_digest(value: str) -> str:
	return hashlib.sha1(value.encode("utf-8")).hexdigest()[:16]
