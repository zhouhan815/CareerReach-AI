from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from boss_agent_cli.rag.models import RagChunk


def load_outreach_playbook_chunks(path: Path) -> list[RagChunk]:
	playbook = json.loads(path.read_text(encoding="utf-8-sig"))
	playbook_id = str(playbook.get("id") or _stable_digest(str(path)))
	base_metadata: dict[str, Any] = {
		"source": "outreach_playbook",
		"source_file": str(path),
		"playbook_id": playbook_id,
		"doc_type": "message_template",
		"company": "",
		"job_title": "",
		"indexed_at": time.time(),
	}
	chunks: list[RagChunk] = []
	rules = playbook.get("outreach_rules") or {}
	if rules:
		chunks.append(
			RagChunk(
				chunk_id=f"outreach_playbook:{playbook_id}:rules",
				text=_render_pairs(
					[
						("话术记忆", playbook.get("description")),
						("Agent 名称", rules.get("agent_name")),
						("开头模板", rules.get("opening_template")),
						("实习开场", rules.get("internship_intro")),
						("收尾", rules.get("closing")),
						("分数展示阈值", rules.get("show_score_threshold")),
						("最高展示分数", rules.get("max_display_score")),
						("JD 括号规则", rules.get("focus_label_rule")),
					]
				),
				metadata={**base_metadata, "chunk_kind": "outreach_rules"},
			)
		)
	for point in playbook.get("core_points", []):
		if not isinstance(point, dict) or not point.get("id"):
			continue
		chunks.append(
			RagChunk(
				chunk_id=f"outreach_playbook:{playbook_id}:core:{point['id']}",
				text=_render_pairs(
					[
						("核心优势ID", point.get("id")),
						("核心优势", point.get("label")),
						("默认话术", point.get("default_text")),
						("命中JD时展开话术", point.get("expanded_text")),
						("JD触发词", "、".join(str(item) for item in point.get("jd_focus_terms", []))),
						("关键词", "、".join(str(item) for item in point.get("keywords", []))),
					]
				),
				metadata={**base_metadata, "chunk_kind": "outreach_core_point", "point_id": str(point.get("id"))},
			)
		)
	for point in playbook.get("supplemental_points", []):
		if not isinstance(point, dict) or not point.get("id"):
			continue
		chunks.append(
			RagChunk(
				chunk_id=f"outreach_playbook:{playbook_id}:supplemental:{point['id']}",
				text=_render_pairs(
					[
						("第七条补充ID", point.get("id")),
						("补充优势", point.get("label")),
						("补充话术", point.get("default_text")),
						("强触发词", "、".join(str(item) for item in point.get("keywords", []))),
					]
				),
				metadata={**base_metadata, "chunk_kind": "outreach_supplemental_point", "point_id": str(point.get("id"))},
			)
		)
	return [chunk for chunk in chunks if chunk.text.strip()]


def _render_pairs(pairs: list[tuple[str, Any]]) -> str:
	lines = [f"{label}: {_text(value)}" for label, value in pairs if _text(value)]
	return "\n".join(lines)


def _text(value: Any) -> str:
	if value is None:
		return ""
	return str(value).strip()


def _stable_digest(value: str) -> str:
	return hashlib.sha1(value.encode("utf-8")).hexdigest()[:16]
