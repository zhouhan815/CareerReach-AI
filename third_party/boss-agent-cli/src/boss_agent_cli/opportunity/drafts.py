from __future__ import annotations

from typing import Any

from boss_agent_cli.opportunity.filters import normalize_text


def _score_phrase(match_score: int) -> str:
	if match_score >= 90:
		return f"匹配度：{match_score}/100"
	return "匹配度较高"


def _job_text(candidate: dict[str, Any]) -> str:
	return normalize_text([
		candidate.get("title"),
		candidate.get("description"),
		candidate.get("company_business"),
		candidate.get("job_requirement_judgment"),
		candidate.get("skills"),
	]).lower()


def _contains_any(text: str, tokens: tuple[str, ...]) -> bool:
	return any(token in text for token in tokens)


def _best_match_label(text: str) -> str:
	checks = (
		("AI 客服", ("智能客服", "客服系统", "客服", "呼叫中心", "联络中心", "外呼", "ccaas")),
		("Agent / 工作流", ("agent", "智能体", "工作流", "dify", "rag", "mcp", "prompt", "编排", "自动化")),
		("海外产品", ("海外", "出海", "跨境", "英文", "英语", "global")),
		("大模型评测", ("模型", "大模型", "llm", "transformer", "评测", "nlp", "多模态")),
		("数据分析", ("数据", "指标", "分析", "bi", "运营")),
		("ToB / SaaS", ("tob", "b端", "saas", "企业服务", "售前", "解决方案")),
	)
	for label, tokens in checks:
		if _contains_any(text, tokens):
			return label
	return "AI 产品实践"


def _primary_experience_bullet(candidate: dict[str, Any]) -> str:
	text = _job_text(candidate)
	if _contains_any(text, ("智能客服", "客服系统", "客服", "呼叫中心", "联络中心", "外呼", "ccaas")):
		return (
			"AI 客服/ToB 场景：在 AI 创业公司参与 Top5 保险客户 AI 客服方案，负责场景定位、竞品分析和可控工作流设计；"
			"试点覆盖日均 4 万次咨询，单笔人工时长由 15 分钟降至 6 分钟，人工客服承接量降低 45%。"
		)
	if _contains_any(text, ("dify", "agent", "智能体", "工作流", "prompt", "编排", "自动化", "rag", "mcp")):
		return (
			"Agent/工作流：使用 LangGraph、RAG 和 MCP 构建双 Agent 求职系统，串联岗位信息处理、长期记忆、"
			"匹配评分与个性化触达，并将这条消息本身作为流程输出。"
		)
	if _contains_any(text, ("模型", "算法", "大模型", "llm", "transformer", "多模态", "nlp", "评测")):
		return (
			"AI 技术理解：有 Transformer 相关论文经历，做过模型结构设计和 RMSE、MAE、R² 等指标验证，"
			"能理解模型能力边界并和技术团队沟通。"
		)
	if _contains_any(text, ("英文", "英语", "海外", "出海", "跨境", "global")):
		return (
			"英国留学与海外产品：具备英文资料阅读和工作沟通能力，能支持出海场景下的竞品分析、用户研究和英文资料整理。"
		)
	if _contains_any(text, ("tob", "b端", "saas", "企业服务", "售前", "解决方案")):
		return (
			"ToB/企业服务：在 AI 创业公司参与保险客户 AI 产品方案，负责场景定位、竞品分析、解决方案设计与可控工作流设计。"
		)
	if _contains_any(text, ("数据", "指标", "分析", "bi", "运营")):
		return (
			"数据与指标意识：在 AI 客服方案中关注转人工率、处理时长、咨询量等业务指标，能把需求拆成可验证的产品指标。"
		)
	return (
		"AI 产品实践：在 AI 创业公司参与保险 AI 客服方案，负责场景定位、竞品分析、解决方案设计与可控工作流设计。"
	)


def _experience_bullets(candidate: dict[str, Any]) -> list[str]:
	primary = _primary_experience_bullet(candidate)
	return [
		primary,
		"Dify 工作流：搭建过智能撰写市场调研报告工作流，包括流程拆解、节点设计和 prompt 优化。",
		"Agent 搭建：使用 LangGraph、RAG 和 MCP 构建双 Agent 系统，实现岗位信息处理、长期记忆与个性化触达。",
		"Vibe Coding：熟练使用 Cursor、Codex 等 Agent 工具辅助需求分析和工作流搭建。",
		"英国留学背景：具备英文资料阅读能力和可作为工作语言的英语听说水平。",
		"AI 技术理解：有 Transformer 相关论文经历，能理解模型能力、评价指标和技术边界。",
	]


def build_greeting_message(candidate: dict[str, Any]) -> str:
	"""Generate the fixed opportunity outreach template agreed with the user."""
	match_score = int(candidate.get("resume_match_score") or 0)
	score_phrase = _score_phrase(match_score)
	match_label = _best_match_label(_job_text(candidate))
	bullets = _experience_bullets(candidate)
	bullet_text = "\n".join(f"{idx}. {bullet}" for idx, bullet in enumerate(bullets, start=1))

	return (
		f"您好，这条消息由我自己搭建的求职 Agent 基于贵公司岗位 JD（{match_label}）和我的简历智能生成；"
		f"Agent 判断我与该岗位{score_phrase}。\n"
		"我目前是 27 届在读硕士，正在寻找 AI 产品经理实习机会，想冒昧咨询：团队是否也接受 AI 产品方向实习生，"
		"或是否可以先以实习形式参与相关工作？\n"
		"我的优势主要有：\n"
		f"{bullet_text}\n"
		"如果团队有实习或项目制机会，期待进一步沟通，感谢！"
	)
