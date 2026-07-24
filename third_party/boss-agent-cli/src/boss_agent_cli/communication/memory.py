from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from boss_agent_cli.communication.models import CommunicationPlan, OpportunityContext


class CommunicationMemoryStore:
	"""Local communication memory for generated plans and later outcome tracking."""

	def __init__(self, data_dir: Path) -> None:
		self._root = data_dir / "communication"
		self._plans_dir = self._root / "plans"
		self._plans_dir.mkdir(parents=True, exist_ok=True)

	def save_plan(self, context: OpportunityContext, plan: CommunicationPlan, *, runtime: dict[str, Any]) -> Path:
		created_at = time.time()
		stem = _safe_stem("-".join(part for part in [context.company, context.job_title, context.job_id] if part))
		if not stem:
			stem = "communication-plan"
		path = self._plans_dir / f"{time.strftime('%Y%m%d-%H%M%S')}-{stem}.json"
		payload = {
			"created_at": created_at,
			"context": context.to_dict(),
			"plan": plan.to_dict(),
			"runtime": runtime,
		}
		path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
		return path


def _safe_stem(value: str) -> str:
	clean = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in value.strip())
	while "--" in clean:
		clean = clean.replace("--", "-")
	return clean.strip("-")[:80]
