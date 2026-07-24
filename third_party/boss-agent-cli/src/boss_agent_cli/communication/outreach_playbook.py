from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from boss_agent_cli.communication.models import CommunicationDraft, OpportunityContext

CAREERREACH_DRAFT_STYLE = "CareerReach六条版"


def load_default_outreach_playbook(data_dir: Path) -> dict[str, Any] | None:
	"""Load the CareerReach outreach playbook from local communication memory."""
	candidates = [
		data_dir / "communication" / "outreach_playbook.json",
		_workspace_root_from_data_dir(data_dir) / "offline-opportunity-agent" / "data" / "memory" / "outreach_playbook.json",
	]
	for path in candidates:
		if not path.exists():
			continue
		try:
			return json.loads(path.read_text(encoding="utf-8-sig"))
		except Exception:
			continue
	return None


def build_playbook_draft(
	context: OpportunityContext,
	playbook: dict[str, Any],
	*,
	evidence_ids: list[str],
) -> CommunicationDraft | None:
	"""Build the user's fixed CareerReach greeting from playbook memory."""
	core_points = [item for item in playbook.get("core_points", []) if isinstance(item, dict)]
	if not core_points:
		return None
	rules = playbook.get("outreach_rules") or {}
	focus_point = _select_focus_point(context, core_points)
	focus_label = _focus_label(context, focus_point) if focus_point else ""
	if not focus_label:
		focus_label = context.job_title or "AI 产品"
	score_phrase = _score_phrase(context, rules)
	agent_name = str(rules.get("agent_name") or "CareerReach Agent")
	opening_template = str(
		rules.get("opening_template")
		or "您好，这条消息由我自己搭建的 {agent_name} 基于贵公司岗位 JD（{focus_label}）和我的简历自动生成；{score_phrase}"
	)
	intro = str(
		rules.get("internship_intro")
		or "我目前是 27 届在读硕士，看到贵公司正在招聘 AI 产品/相关方向实习岗位，希望投递并进一步沟通。"
	)
	closing = str(rules.get("closing") or "期待有机会进一步沟通，感谢！")

	lines = [
		opening_template.format(
			agent_name=agent_name,
			focus_label=focus_label,
			score_phrase=score_phrase,
		),
		intro,
		"我的优势主要有：",
	]
	focus_id = str(focus_point.get("id") or "") if focus_point else ""
	for index, point in enumerate(core_points, start=1):
		is_focus = bool(focus_id and str(point.get("id") or "") == focus_id)
		text = str(point.get("expanded_text") if is_focus and point.get("expanded_text") else point.get("default_text") or "")
		lines.append(f"{index}. {point.get('label')}：{text}")

	supplemental = _select_supplemental_point(context, playbook.get("supplemental_points") or [])
	if supplemental:
		text = str(supplemental.get("default_text") or supplemental.get("expanded_text") or "")
		if text:
			lines.append(f"{len(core_points) + 1}. {supplemental.get('label')}：{text}")
	lines.append(closing)
	return CommunicationDraft(
		style=CAREERREACH_DRAFT_STYLE,
		message="\n".join(lines),
		evidence_ids=evidence_ids[:8],
		why_this_works=(
			"使用本地 outreach_playbook 记忆，固定呈现核心优势；只在 JD/岗位上下文命中时展开重点项，"
			"并按规则追加第七条特殊匹配。"
		),
		risk_flags=[],
	)


def _workspace_root_from_data_dir(data_dir: Path) -> Path:
	try:
		return data_dir.resolve().parents[3]
	except IndexError:
		return data_dir.resolve()


def _select_focus_point(context: OpportunityContext, core_points: list[dict[str, Any]]) -> dict[str, Any] | None:
	text = _jd_context_text(context).lower()
	best: dict[str, Any] | None = None
	best_score = 0
	for point in core_points:
		keywords = [str(item) for item in point.get("jd_focus_terms", []) + point.get("keywords", [])]
		score = sum(1 for keyword in keywords if keyword and keyword.lower() in text)
		if score > best_score:
			best = point
			best_score = score
	return best


def _select_supplemental_point(context: OpportunityContext, points: list[Any]) -> dict[str, Any] | None:
	text = _jd_context_text(context).lower()
	best: dict[str, Any] | None = None
	best_score = 0
	for point in points:
		if not isinstance(point, dict):
			continue
		keywords = [str(item) for item in point.get("keywords", [])]
		score = sum(1 for keyword in keywords if keyword and keyword.lower() in text)
		if score > best_score:
			best = point
			best_score = score
	return best


def _focus_label(context: OpportunityContext, point: dict[str, Any]) -> str:
	text = _jd_context_text(context).lower()
	for term in [str(item) for item in point.get("jd_focus_terms", [])]:
		if term and term.lower() in text:
			return term
	for term in [str(item) for item in point.get("keywords", [])]:
		if term and term.lower() in text:
			return _normal_focus_label(term)
	return ""


def _normal_focus_label(term: str) -> str:
	mapping = {
		"AI客服": "AI 客服",
		"智能客服": "AI 客服",
		"ToB": "ToB 场景",
		"Agent": "Agent/智能体",
		"智能体": "Agent/智能体",
		"Dify": "Dify 工作流",
		"工作流": "工作流",
		"RAG": "知识库/RAG",
		"LLM": "大模型应用",
	}
	return mapping.get(term, term)


def _score_phrase(context: OpportunityContext, rules: dict[str, Any]) -> str:
	score = _extract_score(context)
	threshold = int(rules.get("show_score_threshold") or 80)
	max_display = int(rules.get("max_display_score") or 96)
	if score is not None and score >= threshold:
		template = str(rules.get("high_score_template") or "CareerReach Agent 判断我与该岗位匹配度：{score}/100。")
		return template.format(score=min(score, max_display))
	return str(rules.get("low_score_phrase") or "CareerReach Agent 判断我与该岗位匹配度较高。")


def _extract_score(context: OpportunityContext) -> int | None:
	for key in ("resume_match_score", "match_score", "score", "简历匹配度"):
		value = context.facts.get(key)
		score = _parse_score(value)
		if score is not None:
			return score
	for item in context.evidence:
		score = _parse_score(item.text)
		if score is not None:
			return score
	return None


def _parse_score(value: Any) -> int | None:
	text = str(value or "")
	match = re.search(r"(?:简历匹配度|匹配度|match_score|resume_match_score)\D{0,8}(\d{2,3})", text, re.I)
	if not match:
		if text.strip().isdigit():
			match_value = int(text.strip())
			return match_value if 0 <= match_value <= 100 else None
		return None
	score = int(match.group(1))
	return score if 0 <= score <= 100 else None


def _jd_context_text(context: OpportunityContext) -> str:
	parts = [
		context.company,
		context.job_title,
		context.latest_message,
		str(context.facts.get("company_business") or ""),
		str(context.facts.get("job_requirement_judgment") or ""),
		str(context.facts.get("skills") or ""),
		" ".join(
			item.text
			for item in context.evidence
			if item.text and item.source != "outreach_playbook" and item.doc_type in {"job", "company", ""}
		),
	]
	return "\n".join(part for part in parts if part)
