from __future__ import annotations

from typing import Any


ALLOWED_ACTIONS = {"send", "manual_review", "skip"}


def validate_agent_output(payload: dict[str, Any]) -> list[str]:
	issues: list[str] = []
	if not isinstance(payload, dict):
		return ["error: payload must be a JSON object"]
	if payload.get("ok") is not True:
		issues.append("error: payload.ok must be true for a successful demo run")

	data = payload.get("data")
	if not isinstance(data, dict):
		return [*issues, "error: payload.data must be an object"]

	context = data.get("context")
	plan = data.get("plan")
	if not isinstance(context, dict):
		issues.append("error: data.context must be an object")
	if not isinstance(plan, dict):
		return [*issues, "error: data.plan must be an object"]

	action = plan.get("recommended_action")
	if action not in ALLOWED_ACTIONS:
		issues.append(f"error: recommended_action must be one of {sorted(ALLOWED_ACTIONS)}")

	drafts = plan.get("drafts")
	if not isinstance(drafts, list) or not drafts:
		issues.append("error: plan.drafts must be a non-empty list")
	else:
		for index, draft in enumerate(drafts):
			if not isinstance(draft, dict) or not str(draft.get("message") or "").strip():
				issues.append(f"error: draft {index} must include a message")

	valid_evidence_ids = _context_evidence_ids(context if isinstance(context, dict) else {})
	for evidence_id in plan.get("evidence_ids", []) or []:
		if valid_evidence_ids and evidence_id not in valid_evidence_ids:
			issues.append(f"warning: plan references unknown evidence_id: {evidence_id}")
	for draft in drafts or []:
		if not isinstance(draft, dict):
			continue
		for evidence_id in draft.get("evidence_ids", []) or []:
			if valid_evidence_ids and evidence_id not in valid_evidence_ids:
				issues.append(f"warning: draft references unknown evidence_id: {evidence_id}")

	if action == "send" and plan.get("risk_flags"):
		issues.append("warning: send action includes risk_flags; consider manual_review")
	return issues


def _context_evidence_ids(context: dict[str, Any]) -> set[str]:
	ids: set[str] = set()
	for item in context.get("evidence", []) or []:
		if isinstance(item, dict) and item.get("evidence_id"):
			ids.add(str(item["evidence_id"]))
	return ids
