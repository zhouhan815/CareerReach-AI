from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class RagProgressStore:
	def __init__(self, data_dir: Path, name: str) -> None:
		self.path = data_dir / "rag" / "progress" / f"{name}.json"
		self.path.parent.mkdir(parents=True, exist_ok=True)

	def read(self) -> dict[str, Any] | None:
		if not self.path.exists():
			return None
		try:
			return json.loads(self.path.read_text(encoding="utf-8"))
		except (json.JSONDecodeError, OSError):
			return None

	def write(self, payload: dict[str, Any]) -> dict[str, Any]:
		payload = dict(payload)
		payload["updated_at"] = time.time()
		self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
		return payload

	def start(self, **kwargs: Any) -> dict[str, Any]:
		payload = {
			"status": "in_progress",
			"started_at": time.time(),
			"updated_at": time.time(),
			"processed_rows": 0,
			"indexed_chunks": 0,
			"failed_rows": [],
		}
		payload.update(kwargs)
		return self.write(payload)
