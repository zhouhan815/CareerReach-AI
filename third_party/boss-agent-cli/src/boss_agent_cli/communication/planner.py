from __future__ import annotations

import json
import re
from typing import Any

from boss_agent_cli.ai.service import AIService, AIServiceError
from boss_agent_cli.communication.models import CommunicationDraft, CommunicationPlan, OpportunityContext
from boss_agent_cli.communication.outreach_playbook import CAREERREACH_DRAFT_STYLE, build_playbook_draft
from boss_agent_cli.communication.prompts import COMMUNICATION_SYSTEM_PROMPT, build_communication_prompt


class CommunicationPlanError(RuntimeError):
	"""Raised when Communication Agent plan generation fails."""


class CommunicationPlanner:
	def __init__(
		self,
		*,
		ai_service: AIService | None = None,
		mode: str = "auto",
		outreach_playbook: dict[str, Any] | None = None,
	) -> None:
		self._ai_service = ai_service
		self._mode = mode
		self._outreach_playbook = outreach_playbook

	def plan(self, context: OpportunityContext) -> CommunicationPlan:
		if self._mode == "rules":
			return build_rule_based_plan(context, outreach_playbook=self._outreach_playbook)
		if self._mode == "ai" and self._ai_service is None:
			raise CommunicationPlanError("AI mode requires configured AI service")
		if self._ai_service is not None:
			try:
				return _plan_with_ai(self._ai_service, context)
			except CommunicationPlanError:
				if self._mode == "ai":
					raise
		return build_rule_based_plan(context, outreach_playbook=self._outreach_playbook)


def build_rule_based_plan(context: OpportunityContext, *, outreach_playbook: dict[str, Any] | None = None) -> CommunicationPlan:
	evidence_ids = [item.evidence_id for item in context.evidence[:6]]
	company_point = _best_fact(
		context,
		labels=("公司主要业务", "company business", "business"),
		chunk_kinds=("company_profile", "web_company_research"),
		doc_types=("company",),
	)
	job_point = _best_fact(
		context,
		labels=("岗位需求判断", "skill tags", "任职要求", "岗位职责"),
		chunk_kinds=("job_requirement", "boss_job_detail"),
		doc_types=("job",),
	)
	resume_point = _resume_point(context)

	risk_flags = list(context.risk_flags)
	if len(context.evidence) < 3:
		risk_flags.append("RAG evidence is sparse; review before sending.")
	if not company_point:
		risk_flags.append("Missing company/business evidence.")
	if not job_point:
		risk_flags.append("Missing JD/job requirement evidence.")

	confidence = min(0.92, 0.55 + 0.08 * min(len(context.evidence), 4))
	recommended_action = "send" if confidence >= 0.7 and not context.missing_info else "manual_review"
	if "Missing JD/job requirement evidence." in risk_flags and "Missing company/business evidence." in risk_flags:
		recommended_action = "manual_review"

	company = context.company or "贵公司"
	job_title = context.job_title or "这个岗位"
	intro = _goal_intro(context.goal)
	resume_phrase = resume_point or "我有 AI 产品、RAG/Agent 工作流和需求分析相关实践"
	company_phrase = _compact(company_point, 34) or "贵公司的业务方向"
	job_phrase = _compact(job_point, 36) or "岗位要求"

	drafts: list[CommunicationDraft] = []
	if outreach_playbook:
		playbook_draft = build_playbook_draft(context, outreach_playbook, evidence_ids=evidence_ids)
		if playbook_draft:
			drafts.append(playbook_draft)
	drafts.extend([
		CommunicationDraft(
			style="稳妥版",
			message=(
				f"您好，我关注到{company}的{job_title}。{intro}"
				f"我留意到{company_phrase}，也看到岗位关注{job_phrase}。"
				f"{resume_phrase}，想请问团队是否接受进一步沟通？"
			),
			evidence_ids=evidence_ids[:4],
			why_this_works="把公司业务、岗位要求和个人经历放在同一条证据链里，语气稳妥。",
			risk_flags=[],
		),
		CommunicationDraft(
			style="主动版",
			message=(
				f"您好，我用自己的求职 Agent 对{company}的{job_title}做了匹配分析。"
				f"岗位与{resume_phrase}比较相关，尤其是{job_phrase}。"
				"如果方便，我想进一步了解团队当前最希望候选人解决的产品问题。"
			),
			evidence_ids=evidence_ids[:4],
			why_this_works="突出 Agent 项目本身，适合 AI 产品或 Agent 相关岗位。",
			risk_flags=[],
		),
		CommunicationDraft(
			style="简洁版",
			message=(
				f"您好，我对{company}的{job_title}很感兴趣。"
				f"我的经历和{job_phrase}较匹配，尤其是{resume_phrase}。"
				"想请问可以进一步沟通岗位要求和实习/项目机会吗？"
			),
			evidence_ids=evidence_ids[:3],
			why_this_works="信息密度高，适合 BOSS 初次沟通。",
			risk_flags=[],
		),
	])
	return CommunicationPlan(
		communication_goal=context.goal,
		recommended_action=recommended_action,
		drafts=[_trim_draft(draft) for draft in drafts],
		follow_up_plan="若 2-3 天无回复，可基于公司业务点补充一个更具体的问题；若对方回复，优先确认岗位核心任务和实习/到岗安排。",
		evidence_ids=evidence_ids,
		risk_flags=_dedupe(risk_flags),
		confidence=round(confidence, 2),
		agent_notes=[
			"Boss Data Agent 负责事实和 RAG 检索；Communication Agent 只生成沟通策略和话术。",
			"规则模式未调用外部模型，可作为 AI 模式失败时的稳定 fallback。",
		],
	)


def _plan_with_ai(ai_service: AIService, context: OpportunityContext) -> CommunicationPlan:
	try:
		raw = ai_service.chat(
			[
				{"role": "system", "content": COMMUNICATION_SYSTEM_PROMPT},
				{"role": "user", "content": build_communication_prompt(context)},
			],
			temperature=0.4,
			max_tokens=1800,
		)
	except AIServiceError as exc:
		raise CommunicationPlanError(str(exc)) from exc
	text = raw.strip()
	if text.startswith("```"):
		lines = [line for line in text.splitlines() if not line.startswith("```")]
		text = "\n".join(lines).strip()
	try:
		data = json.loads(text)
	except json.JSONDecodeError as exc:
		raise CommunicationPlanError("AI response is not valid JSON") from exc
	if not isinstance(data, dict):
		raise CommunicationPlanError("AI response must be a JSON object")
	plan = CommunicationPlan.from_dict(data)
	return validate_plan(plan, context)


def validate_plan(plan: CommunicationPlan, context: OpportunityContext) -> CommunicationPlan:
	valid_ids = {item.evidence_id for item in context.evidence}
	risk_flags = list(plan.risk_flags)
	for draft in plan.drafts:
		for evidence_id in draft.evidence_ids:
			if evidence_id not in valid_ids:
				risk_flags.append(f"Draft references unknown evidence_id: {evidence_id}")
	if not plan.drafts:
		risk_flags.append("Communication Agent returned no drafts.")
	recommended_action = plan.recommended_action
	if risk_flags and recommended_action == "send":
		recommended_action = "manual_review"
	return CommunicationPlan(
		communication_goal=plan.communication_goal,
		recommended_action=recommended_action,
		drafts=plan.drafts,
		follow_up_plan=plan.follow_up_plan,
		evidence_ids=plan.evidence_ids,
		risk_flags=_dedupe(risk_flags),
		confidence=plan.confidence,
		agent_notes=plan.agent_notes,
	)


def _goal_intro(goal: str) -> str:
	if goal == "follow_up":
		return "想基于前次沟通再补充一点我的匹配点。"
	if goal == "reply":
		return "结合您刚才的信息，我想补充说明我的相关经历。"
	if goal == "interview_confirm":
		return "我想确认面试安排，并提前对齐岗位重点。"
	return "我想先简短说明一下自己和岗位的匹配点。"


def _best_fact(
	context: OpportunityContext,
	*,
	labels: tuple[str, ...],
	chunk_kinds: tuple[str, ...],
	doc_types: tuple[str, ...],
) -> str:
	preferred = [item for item in context.evidence if item.chunk_kind in chunk_kinds]
	preferred.extend(
		item for item in context.evidence if item.doc_type in doc_types and item not in preferred
	)
	preferred.extend(
		item for item in context.evidence if item.source == "direct_input" and item not in preferred
	)
	expanded_labels = (
		*labels,
		"job requirement",
		"job requirements",
		"job_requirement",
	)
	for item in preferred:
		value = _line_value(item.text, expanded_labels)
		if value:
			return value
	for item in preferred:
		if item.text:
			return _strip_label(item.text)
	return ""


def _resume_point(context: OpportunityContext) -> str:
	for key in ("resume_evidence", "match_reasons", "skills"):
		value = context.facts.get(key)
		if value and not _is_score_like(value):
			return _compact(_stringify(value), 44)
	for item in context.evidence:
		if item.chunk_kind != "outreach_context":
			continue
		for line in item.text.splitlines():
			match = re.match(r"^\s*\d+[.、]\s*[^:：]{1,24}[:：]\s*(.+)$", line)
			if match:
				return _compact(match.group(1).strip(), 44)
	for item in context.evidence:
		text = item.text
		lower = text.lower()
		if item.doc_type == "resume" or any(
			token in lower for token in ("resume", "简历证据", "个人经历", "项目经历", "经历证据", "match_reasons")
		):
			stripped = _strip_label(text)
			if not _is_score_like(stripped):
				return _compact(stripped, 44)
	for item in context.evidence:
		value = _line_value(item.text, ("匹配理由", "match reasons"))
		if value and not _is_score_like(value):
			return _compact(value, 44)
	return ""


def _line_value(text: str, labels: tuple[str, ...]) -> str:
	for line in text.splitlines():
		clean = line.strip()
		lower = clean.lower()
		for label in labels:
			label_lower = _label_key(label)
			if ":" in clean:
				head, remainder = clean.split(":", 1)
				if _label_key(head) == label_lower and remainder.strip():
					return remainder.strip()
			if not _label_key(lower).startswith(label_lower):
				continue
			remainder = clean[len(label) :].lstrip(" :：-")
			if remainder:
				return remainder
	return ""


def _label_key(value: str) -> str:
	return " ".join(value.lower().replace("_", " ").split())


def _trim_draft(draft: CommunicationDraft) -> CommunicationDraft:
	if draft.style in {CAREERREACH_DRAFT_STYLE, "CareerReach???"}:
		message = draft.message.strip()
	else:
		message = " ".join(draft.message.split())
	return CommunicationDraft(
		style=draft.style,
		message=message,
		evidence_ids=draft.evidence_ids,
		why_this_works=draft.why_this_works,
		risk_flags=draft.risk_flags,
	)


def _compact(text: str, limit: int) -> str:
	clean = " ".join(text.replace("\n", " ").split())
	if len(clean) <= limit:
		return clean
	return clean[: max(0, limit - 1)] + "..."


def _strip_label(text: str) -> str:
	clean = " ".join(text.replace("\n", " ").split())
	for sep in (":", "："):
		if sep in clean:
			left, right = clean.split(sep, 1)
			left_key = left.strip().lower().replace("_", " ")
			label_like = len(left) <= 32 and any(
				token in left_key
				for token in (
					"company",
					"business",
					"job",
					"requirement",
					"resume",
					"evidence",
					"match",
					"reason",
					"公司",
					"业务",
					"岗位",
					"职位",
					"简历",
					"证据",
					"匹配",
				)
			)
			if label_like and right.strip():
				return right.strip()
	return clean


def _stringify(value: Any) -> str:
	if isinstance(value, list):
		return "；".join(str(item) for item in value if item)
	return str(value)


def _is_score_like(value: Any) -> bool:
	text = _stringify(value).strip()
	if not text:
		return True
	if len(text) <= 5 and text.replace(".", "", 1).isdigit():
		return True
	label, sep, right = text.partition(":")
	if sep:
		label_key = label.strip().lower()
		if label_key in {"resume_match_score", "match_score", "score"}:
			return True
		if len(right.strip()) <= 5 and right.strip().replace(".", "", 1).isdigit():
			return True
	return False


def _dedupe(items: list[str]) -> list[str]:
	seen: set[str] = set()
	out: list[str] = []
	for item in items:
		if item and item not in seen:
			seen.add(item)
			out.append(item)
	return out
