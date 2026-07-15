from __future__ import annotations

from typing import Any


def build_fixture_output(seed: dict[str, Any]) -> dict[str, Any]:
	company = str(seed.get("company") or "示例公司")
	job_title = str(seed.get("job_title") or seed.get("title") or "AI 产品经理")
	goal = str(seed.get("goal") or "initial_outreach")
	facts = seed.get("facts") if isinstance(seed.get("facts"), dict) else {}

	company_point = _fact(seed, "company_business", "公司主要业务")
	job_point = _fact(seed, "job_requirement_judgment", "岗位需求")
	resume_point = _fact(seed, "resume_evidence", "简历证据") or _fact(seed, "match_reasons", "匹配理由")

	evidence = []
	if company_point:
		evidence.append(_evidence("company:demo", company_point, "company", "company_profile", company, job_title))
	if job_point:
		evidence.append(_evidence("job:demo", job_point, "job", "job_requirement", company, job_title))
	if resume_point:
		evidence.append(_evidence("resume:demo", resume_point, "resume", "resume_profile", company, job_title))

	missing_info = []
	if not company:
		missing_info.append("company")
	if not job_title:
		missing_info.append("job_title")
	if not evidence:
		missing_info.append("rag_evidence")

	risk_flags = []
	if not company_point:
		risk_flags.append("Missing company/business evidence.")
	if not job_point:
		risk_flags.append("Missing JD/job requirement evidence.")
	if len(evidence) < 3:
		risk_flags.append("RAG evidence is sparse; review before sending.")

	confidence = 0.55 + min(len(evidence), 3) * 0.08
	recommended_action = "send" if confidence >= 0.7 and not risk_flags else "manual_review"
	evidence_ids = [item["evidence_id"] for item in evidence]

	plan = {
		"communication_goal": goal,
		"recommended_action": recommended_action,
		"drafts": [
			{
				"style": "稳妥版",
				"message": (
					f"您好，我关注到{company}的 {job_title}。我留意到{company_point or '贵公司的业务方向'}，"
					f"也看到岗位关注 {job_point or 'AI 产品能力'}。{resume_point or '我有 AI Agent 和产品分析相关实践'}，"
					"想请问团队是否方便进一步沟通？"
				),
				"evidence_ids": evidence_ids,
				"why_this_works": "把公司业务、岗位要求和个人经历放在同一条证据链中，适合首次沟通。",
				"risk_flags": [],
			},
			{
				"style": "Agent 项目版",
				"message": (
					f"您好，我最近做了一个求职沟通 Agent demo，会用 RAG 证据链分析岗位匹配度。"
					f"我看到{company}的 {job_title}与「{resume_point or '我的 AI 产品实践'}」比较相关，"
					"希望有机会了解团队当前最需要候选人解决的产品问题。"
				),
				"evidence_ids": evidence_ids,
				"why_this_works": "突出 Agent 项目本身，适合 AI Agent / AI 产品经理岗位。",
				"risk_flags": [],
			},
		],
		"follow_up_plan": "若 2-3 天无回复，基于公司业务点补充一个更具体的问题；若对方回复，优先确认岗位核心任务、到岗时间和协作方式。",
		"evidence_ids": evidence_ids,
		"risk_flags": risk_flags,
		"confidence": round(confidence, 2),
		"agent_notes": [
			"Boss Data Agent 负责事实和 RAG 证据；Communication Agent 负责沟通策略和话术。",
			"Codex Supervisor 保留最终判断，敏感动作进入人工审核。",
		],
	}

	return {
		"ok": True,
		"command": "careerreach ai demo",
		"data": {
			"context": {
				"company": company,
				"job_title": job_title,
				"goal": goal,
				"facts": facts,
				"evidence": evidence,
				"missing_info": missing_info,
				"risk_flags": [],
			},
			"plan": plan,
			"runtime": {
				"orchestrator": "codex_supervisor_fixture",
				"upstream_cli": "boss-agent-cli compatible",
				"rag_backend": "sampled_chromadb_contract",
			},
		},
		"hints": {
			"next_actions": [
				"Review evidence_ids before sending.",
				"Switch to --backend boss when boss-agent-cli is installed.",
			]
		},
	}


def _evidence(
	evidence_id: str,
	text: str,
	doc_type: str,
	chunk_kind: str,
	company: str,
	job_title: str,
) -> dict[str, Any]:
	return {
		"evidence_id": evidence_id,
		"text": text,
		"source": "synthetic_demo",
		"doc_type": doc_type,
		"chunk_kind": chunk_kind,
		"company": company,
		"job_title": job_title,
		"score": 0.91,
	}


def _fact(seed: dict[str, Any], key: str, label: str) -> str:
	facts = seed.get("facts") if isinstance(seed.get("facts"), dict) else {}
	if facts.get(key):
		return str(facts[key]).strip()
	for line in seed.get("extra_context", []) or []:
		text = str(line).strip()
		if text.startswith(f"{label}:") or text.startswith(f"{label}："):
			return text.split(":", 1)[-1].split("：", 1)[-1].strip()
	return ""
