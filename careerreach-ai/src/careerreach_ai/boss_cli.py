from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any


class BossCliError(RuntimeError):
	"""Raised when the underlying boss CLI cannot produce a valid JSON result."""


def build_boss_command(
	seed: dict[str, Any],
	*,
	executable: str = "boss",
	mode: str = "rules",
	use_rag: bool = False,
	save: bool = False,
	data_dir: Path | None = None,
) -> list[str]:
	command = [executable]
	if data_dir is not None:
		command.extend(["--data-dir", str(data_dir)])
	command.extend(["--json", "ai", "communication", "plan"])

	company = str(seed.get("company") or "")
	job_title = str(seed.get("job_title") or seed.get("title") or "")
	if company:
		command.extend(["--company", company])
	if job_title:
		command.extend(["--job-title", job_title])
	if seed.get("goal"):
		command.extend(["--goal", str(seed["goal"])])
	if seed.get("latest_message"):
		command.extend(["--latest-message", str(seed["latest_message"])])

	for line in context_lines(seed):
		command.extend(["--context", line])

	command.extend(["--mode", mode])
	command.append("--use-rag" if use_rag else "--no-rag")
	command.append("--save" if save else "--no-save")
	return command


def run_boss_communication_plan(
	seed: dict[str, Any],
	*,
	executable: str = "boss",
	mode: str = "rules",
	use_rag: bool = False,
	save: bool = False,
	data_dir: Path | None = None,
) -> dict[str, Any]:
	command = build_boss_command(
		seed,
		executable=executable,
		mode=mode,
		use_rag=use_rag,
		save=save,
		data_dir=data_dir,
	)
	env = os.environ.copy()
	env.setdefault("PYTHONUTF8", "1")
	env.setdefault("PYTHONIOENCODING", "utf-8")
	try:
		completed = subprocess.run(command, capture_output=True, check=False, env=env)
	except FileNotFoundError as exc:
		raise BossCliError("boss CLI is not installed or not on PATH.") from exc

	stdout = _decode_output(completed.stdout)
	stderr = _decode_output(completed.stderr)
	if completed.returncode != 0:
		raise BossCliError(stderr.strip() or stdout.strip() or "boss CLI failed.")
	try:
		return json.loads(stdout)
	except json.JSONDecodeError as exc:
		raise BossCliError("boss CLI returned non-JSON output.") from exc


def _decode_output(value: bytes | None) -> str:
	if not value:
		return ""
	for encoding in ("utf-8", "utf-8-sig", "gb18030"):
		try:
			return value.decode(encoding)
		except UnicodeDecodeError:
			continue
	return value.decode("utf-8", errors="replace")


def context_lines(seed: dict[str, Any]) -> list[str]:
	facts = seed.get("facts") if isinstance(seed.get("facts"), dict) else {}
	lines: list[str] = []
	mapping = {
		"company_business": "公司主要业务",
		"job_requirement_judgment": "岗位需求",
		"resume_evidence": "简历证据",
		"match_reasons": "匹配理由",
	}
	for key, label in mapping.items():
		value = facts.get(key)
		if value:
			lines.append(f"{label}: {value}")
	for item in seed.get("extra_context", []) or []:
		text = str(item).strip()
		if text and text not in lines:
			lines.append(text)
	return lines
