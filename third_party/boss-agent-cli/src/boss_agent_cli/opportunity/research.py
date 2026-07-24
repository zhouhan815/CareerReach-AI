from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import quote_plus

import httpx

from boss_agent_cli.opportunity.filters import normalize_text

_BUSINESS_HINTS = (
	("AI 客服/智能客服", ("客服", "坐席", "呼叫中心", "工单", "对话")),
	("大模型应用/智能体", ("大模型", "llm", "agent", "智能体", "aigc", "生成式")),
	("企业服务/SaaS", ("tob", "b端", "企业服务", "saas", "crm", "erp")),
	("数据分析/BI", ("数据分析", "bi", "指标", "报表", "数据产品")),
	("营销增长/广告", ("营销", "增长", "广告", "投放", "私域")),
	("金融/保险科技", ("金融", "保险", "风控", "理赔", "投顾")),
	("教育科技", ("教育", "学习", "课程", "教研")),
	("跨境/出海", ("跨境", "出海", "海外", "英文")),
)


def infer_company_business(candidate: dict[str, Any]) -> str:
	industry = normalize_text(candidate.get("industry"))
	description = normalize_text(candidate.get("description"))
	title = normalize_text(candidate.get("title"))
	skills = normalize_text(candidate.get("skills"))
	text = f"{industry} {description} {title} {skills}".lower()

	matches = [label for label, keywords in _BUSINESS_HINTS if any(keyword.lower() in text for keyword in keywords)]
	if matches:
		return "、".join(matches[:3])
	if industry:
		return f"{industry}相关业务"
	return "业务方向待进一步确认"


def summarize_job_requirement(candidate: dict[str, Any]) -> str:
	description = normalize_text(candidate.get("description"))
	skills = candidate.get("skills") or []
	if not isinstance(skills, list):
		skills = []
	skill_text = "、".join(str(skill) for skill in skills[:6] if str(skill).strip())
	business = normalize_text(candidate.get("company_business")) or infer_company_business(candidate)

	judgments: list[str] = []
	if skill_text:
		judgments.append(f"技能标签：{skill_text}")
	if description:
		for label, keywords in _BUSINESS_HINTS:
			if any(keyword.lower() in description.lower() for keyword in keywords):
				judgments.append(f"JD 指向：{label}")
				break
	if business:
		judgments.append(f"结合公司业务判断：岗位可能服务于{business}")
	return "；".join(judgments) if judgments else "JD 信息较少，需在沟通中确认具体应用场景"


def web_research_company(company: str, *, timeout: float = 5.0) -> str:
	"""Best-effort public web snippet. The workflow never depends on this succeeding."""
	query = quote_plus(f"{company} 公司 业务")
	url = f"https://duckduckgo.com/html/?q={query}"
	try:
		response = httpx.get(url, timeout=timeout, follow_redirects=True)
		response.raise_for_status()
	except Exception:
		return ""
	text = html.unescape(response.text)
	text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", text, flags=re.S | re.I)
	text = re.sub(r"<[^>]+>", " ", text)
	text = re.sub(r"\s+", " ", text)
	index = text.find(company)
	if index == -1:
		return ""
	start = max(0, index - 80)
	end = min(len(text), index + 260)
	return text[start:end].strip()
