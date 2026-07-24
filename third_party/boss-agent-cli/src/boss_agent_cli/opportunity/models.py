from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class OpportunityScores:
	"""Local scoring result for a role and the user's resume."""

	resume_match_score: int
	internship_acceptance_score: int
	recommendation_level: str
	match_reasons: list[str] = field(default_factory=list)
	acceptance_reasons: list[str] = field(default_factory=list)
	risk_reasons: list[str] = field(default_factory=list)

	def to_dict(self) -> dict[str, Any]:
		return asdict(self)


@dataclass
class OpportunityCandidate:
	"""A stored candidate role in the AI product manager opportunity workflow."""

	candidate_id: str
	run_id: str
	status: str
	query: str
	city: str
	title: str
	company: str
	salary: str
	location: str
	company_scale: str
	company_stage: str
	industry: str
	experience: str
	education: str
	security_id: str
	job_id: str
	lid: str = ""
	boss_name: str = ""
	boss_title: str = ""
	description: str = ""
	skills: list[str] = field(default_factory=list)
	welfare: list[str] = field(default_factory=list)
	company_business: str = ""
	job_requirement_judgment: str = ""
	weekly_days: str = "待沟通"
	internship_duration: str = "待沟通"
	resume_match_score: int = 0
	internship_acceptance_score: int = 0
	recommendation_level: str = "C"
	match_reasons: list[str] = field(default_factory=list)
	acceptance_reasons: list[str] = field(default_factory=list)
	risk_reasons: list[str] = field(default_factory=list)
	greeting_message: str = ""
	excluded_reason: str = ""
	payload: dict[str, Any] = field(default_factory=dict)
	created_at: float = 0.0
	updated_at: float = 0.0

	def to_dict(self) -> dict[str, Any]:
		return asdict(self)

	@classmethod
	def from_dict(cls, data: dict[str, Any]) -> "OpportunityCandidate":
		known = {field_name for field_name in cls.__dataclass_fields__}
		values = {key: value for key, value in data.items() if key in known}
		return cls(**values)
