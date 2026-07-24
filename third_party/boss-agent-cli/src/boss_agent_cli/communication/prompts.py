from __future__ import annotations

import json

from boss_agent_cli.communication.models import OpportunityContext


COMMUNICATION_SYSTEM_PROMPT = (
	"你是求职场景的 Communication Agent，只负责沟通策略和话术。"
	"你必须基于 evidence_ids 引用事实，不编造公司、岗位或简历经历。"
	"输出必须是 JSON，不要包含 markdown。"
)


def build_communication_prompt(context: OpportunityContext) -> str:
	payload = {
		"task": "Generate an evidence-backed communication plan for a job opportunity.",
		"context": context.to_dict(),
		"output_schema": {
			"communication_goal": "string",
			"recommended_action": "send | manual_review | skip",
			"drafts": [
				{
					"style": "稳妥版 | 主动版 | 简洁版",
					"message": "80-180 Chinese chars for initial outreach unless the goal needs otherwise",
					"evidence_ids": ["string"],
					"why_this_works": "string",
					"risk_flags": ["string"],
				}
			],
			"follow_up_plan": "string",
			"evidence_ids": ["string"],
			"risk_flags": ["string"],
			"confidence": "0-1 number",
			"agent_notes": ["string"],
		},
		"rules": [
			"Use at least one company/business evidence item when available.",
			"Use at least one job requirement evidence item when available.",
			"Use resume evidence only if it is present in context.",
			"Mark manual_review when key evidence is missing or confidence is below 0.7.",
			"Never claim internship acceptance unless the evidence supports it.",
		],
	}
	return json.dumps(payload, ensure_ascii=False, indent=2)
