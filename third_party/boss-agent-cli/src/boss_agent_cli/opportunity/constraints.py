from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from boss_agent_cli.opportunity.filters import normalize_text


@dataclass
class FitConstraints:
	"""Role-specific fit constraints that sit outside generic AI PM keyword matching."""

	hard_exclusion_reasons: list[str] = field(default_factory=list)
	soft_gap_reasons: list[str] = field(default_factory=list)
	soft_gap_penalty: int = 0


_MANDATORY_MARKERS = (
	"必须",
	"必备",
	"必须项",
	"硬性",
	"强制",
	"不匹配",
	"不符合",
	"required",
	"must",
)

_MANDATORY_TOOL_GROUPS = (
	(
		"WorkBuddy / Genspark / Hermes",
		("workbuddy", "work buddy", "genspark", "hermes"),
	),
)

_SOFT_GAP_GROUPS = (
	(
		"机器人/运动控制",
		("机器人", "机械臂", "运动控制", "控制算法", "ros", "slam", "导航控制", "伺服", "驱动器"),
		("机器人", "机械臂", "运动控制", "ros", "slam", "导航控制"),
		22,
	),
	(
		"资金/财务系统",
		("资金", "财务", "会计", "结算", "对账", "应收", "应付", "预算", "报销", "收付款"),
		("资金", "财务", "会计", "结算", "对账", "应收", "应付", "预算", "报销"),
		18,
	),
	(
		"金融/投资行业知识",
		("金融", "基金", "证券", "投资", "投顾", "理财", "资管", "量化", "股票", "债券"),
		("金融", "基金", "证券", "投资", "投顾", "理财", "资管", "量化"),
		20,
	),
	(
		"审美/视觉设计能力",
		("审美", "美学", "视觉设计", "ui设计", "交互设计", "设计功底", "作品集"),
		("审美", "美学", "视觉设计", "ui设计", "交互设计", "设计作品集"),
		15,
	),
)


def _job_text(candidate: dict[str, Any]) -> str:
	parts = [
		candidate.get("title"),
		candidate.get("company"),
		candidate.get("industry"),
		candidate.get("description"),
		normalize_text(candidate.get("skills")),
		candidate.get("company_business"),
		candidate.get("job_requirement_judgment"),
	]
	return normalize_text(parts).lower()


def _has_any(text: str, tokens: tuple[str, ...]) -> bool:
	return any(token.lower() in text for token in tokens)


def assess_fit_constraints(candidate: dict[str, Any], resume_text: str) -> FitConstraints:
	"""Detect hard mandatory gaps and softer domain gaps for opportunity ranking."""
	job_text = _job_text(candidate)
	resume_lower = resume_text.lower()
	result = FitConstraints()

	for label, tokens in _MANDATORY_TOOL_GROUPS:
		if _has_any(job_text, tokens) and _has_any(job_text, _MANDATORY_MARKERS) and not _has_any(resume_lower, tokens):
			result.hard_exclusion_reasons.append(f"JD 将 {label} 标为必须项，但简历中没有对应工具使用证据")

	for label, job_tokens, resume_tokens, penalty in _SOFT_GAP_GROUPS:
		if _has_any(job_text, job_tokens) and not _has_any(resume_lower, resume_tokens):
			result.soft_gap_reasons.append(f"岗位明显涉及{label}，但简历中缺少对应背景，匹配度扣 {penalty} 分")
			result.soft_gap_penalty += penalty

	return result
