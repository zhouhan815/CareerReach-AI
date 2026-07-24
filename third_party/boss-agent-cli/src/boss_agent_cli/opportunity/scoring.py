from __future__ import annotations

from typing import Any

from boss_agent_cli.opportunity.constraints import assess_fit_constraints
from boss_agent_cli.opportunity.filters import normalize_text, parse_company_scale, parse_salary_k_range
from boss_agent_cli.opportunity.models import OpportunityScores

_AI_PM_KEYWORDS = {
	"AI产品": ("ai产品", "ai 产品", "大模型产品", "智能体", "agent", "aigc", "产品经理"),
	"需求与竞品": ("需求分析", "竞品", "原型", "prd", "用户调研", "场景"),
	"工作流": ("dify", "工作流", "prompt", "提示词", "编排", "自动化"),
	"ToB/客服": ("tob", "b端", "企业服务", "客服", "保险", "saas"),
	"技术理解": ("transformer", "模型", "算法", "评测", "数据", "api"),
	"英语/出海": ("英语", "英文", "海外", "出海", "跨境"),
}

_HIGH_RESPONSIBILITY_TOKENS = ("负责人", "专家", "高级", "资深", "带团队", "0-1负责", "商业化负责人")
_FLEXIBLE_TOKENS = ("成长", "培养", "应届", "经验不限", "1-3年", "初级", "团队扩张", "快速迭代")


def _text_for_job(job: dict[str, Any]) -> str:
	parts = [
		job.get("title"),
		job.get("company"),
		job.get("industry"),
		job.get("description"),
		job.get("company_business"),
		job.get("job_requirement_judgment"),
		normalize_text(job.get("skills")),
	]
	return normalize_text(parts).lower()


def score_resume_match(job: dict[str, Any], resume_text: str) -> tuple[int, list[str], list[str]]:
	"""Score how well the role matches the user's AI PM resume."""
	job_text = _text_for_job(job)
	resume_lower = resume_text.lower()
	score = 45
	reasons: list[str] = []
	risks: list[str] = []

	if "产品经理" in job_text or "ai产品" in job_text or "ai 产品" in job_text:
		score += 12
		reasons.append("岗位关键词与 AI 产品经理经历相关")

	for label, keywords in _AI_PM_KEYWORDS.items():
		job_hit = any(keyword.lower() in job_text for keyword in keywords)
		resume_hit = any(keyword.lower() in resume_lower for keyword in keywords)
		if job_hit and resume_hit:
			score += 7
			reasons.append(f"JD 与简历都覆盖{label}")
		elif job_hit:
			score += 3
			reasons.append(f"JD 明确需要{label}能力")

	if any(token in job_text for token in ("本科", "硕士", "研究生")) and "硕士" in resume_text:
		score += 4
		reasons.append("学历背景满足岗位筛选条件")
	if any(token in job_text for token in ("3-5年", "5-10年", "资深", "专家")):
		score -= 10
		risks.append("岗位可能偏正式经验或 senior 要求")
	if not normalize_text(job.get("description")):
		score -= 6
		risks.append("JD 描述不足，匹配判断依赖列表字段")

	constraints = assess_fit_constraints(job, resume_text)
	if constraints.soft_gap_penalty:
		score -= constraints.soft_gap_penalty
		risks.extend(constraints.soft_gap_reasons)
	if constraints.hard_exclusion_reasons:
		score -= 45
		risks.extend(constraints.hard_exclusion_reasons)

	return max(0, min(100, score)), reasons[:6], risks[:5]


def score_internship_acceptance(job: dict[str, Any]) -> tuple[int, list[str], list[str]]:
	"""Estimate whether a formal role may accept an internship arrangement."""
	text = _text_for_job(job)
	scale = normalize_text(job.get("company_scale") or job.get("scale"))
	experience = normalize_text(job.get("experience"))
	salary = normalize_text(job.get("salary"))
	min_scale, max_scale = parse_company_scale(scale)
	min_salary, max_salary = parse_salary_k_range(salary)
	score = 50
	reasons: list[str] = []
	risks: list[str] = []

	if min_scale is not None and max_scale is not None and 20 <= min_scale and max_scale <= 500:
		score += 22
		reasons.append("公司规模处于 20-500 人，通常更可能灵活接收实习生")
	elif min_scale is not None and max_scale is not None and 500 < max_scale < 1000:
		score -= 4
		risks.append("公司规模为 500-999 人，仍可沟通但临时开放实习机会的概率低于中小团队")
	elif min_scale is not None and max_scale is not None and max_scale < 20:
		score += 8
		reasons.append("小团队可能有灵活空间，但带教资源需确认")
	elif min_scale is not None and min_scale >= 1000:
		score -= 35
		risks.append("公司规模 1000 人以上，正式岗流程通常不适合作为实习机会沟通对象")
	elif scale:
		score += 6
		reasons.append("公司规模信息可用于进一步人工判断")

	if any(token in experience for token in ("经验不限", "应届", "1-3")):
		score += 16
		reasons.append("经验要求较低，存在实习切入可能")
	elif any(token in experience for token in ("3-5", "5-10", "10年以上")):
		score -= 14
		risks.append(f"经验要求为 {experience}，可能更偏正式员工")

	if max_salary is not None and max_salary >= 35:
		score -= 10
		risks.append("薪资上限较高，岗位责任可能较重")
	elif max_salary is not None and max_salary <= 25:
		score += 6
		reasons.append("薪资段未明显指向高阶岗位")

	if any(token in text for token in _FLEXIBLE_TOKENS):
		score += 8
		reasons.append("JD 出现培养/成长/低年限等灵活信号")
	if any(token in text for token in _HIGH_RESPONSIBILITY_TOKENS):
		score -= 10
		risks.append("JD 出现负责人/专家/带团队等高责任信号")

	return max(0, min(100, score)), reasons[:6], risks[:5]


def recommendation_level(match_score: int, acceptance_score: int) -> str:
	if match_score >= 82 and acceptance_score >= 70:
		return "A"
	if match_score >= 72 and acceptance_score >= 58:
		return "B"
	return "C"


def score_opportunity(job: dict[str, Any], resume_text: str) -> OpportunityScores:
	match_score, match_reasons, match_risks = score_resume_match(job, resume_text)
	acceptance_score, acceptance_reasons, acceptance_risks = score_internship_acceptance(job)
	level = recommendation_level(match_score, acceptance_score)
	return OpportunityScores(
		resume_match_score=match_score,
		internship_acceptance_score=acceptance_score,
		recommendation_level=level,
		match_reasons=match_reasons,
		acceptance_reasons=acceptance_reasons,
		risk_reasons=[*match_risks, *acceptance_risks],
	)
