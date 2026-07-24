from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class EvidenceItem:
	"""A traceable fact chunk retrieved from the career RAG store."""

	evidence_id: str
	text: str
	source: str = ""
	doc_type: str = ""
	chunk_kind: str = ""
	company: str = ""
	job_title: str = ""
	job_id: str = ""
	score: float | None = None

	def to_dict(self) -> dict[str, Any]:
		return asdict(self)


@dataclass(frozen=True, slots=True)
class OpportunitySeed:
	"""Minimal user/task input used by the Boss Data Agent."""

	company: str = ""
	job_title: str = ""
	job_id: str = ""
	security_id: str = ""
	contact_id: str = ""
	goal: str = "initial_outreach"
	latest_message: str = ""
	extra_context: list[str] = field(default_factory=list)
	facts: dict[str, Any] = field(default_factory=dict)

	def to_dict(self) -> dict[str, Any]:
		return asdict(self)


@dataclass(frozen=True, slots=True)
class OpportunityContext:
	"""Structured context handed from Boss Data Agent to Communication Agent."""

	company: str
	job_title: str
	job_id: str = ""
	security_id: str = ""
	contact_id: str = ""
	goal: str = "initial_outreach"
	latest_message: str = ""
	facts: dict[str, Any] = field(default_factory=dict)
	evidence: list[EvidenceItem] = field(default_factory=list)
	missing_info: list[str] = field(default_factory=list)
	risk_flags: list[str] = field(default_factory=list)

	def to_dict(self) -> dict[str, Any]:
		data = asdict(self)
		data["evidence"] = [item.to_dict() for item in self.evidence]
		return data


@dataclass(frozen=True, slots=True)
class CommunicationDraft:
	"""One candidate message produced by the Communication Agent."""

	style: str
	message: str
	evidence_ids: list[str] = field(default_factory=list)
	why_this_works: str = ""
	risk_flags: list[str] = field(default_factory=list)

	def to_dict(self) -> dict[str, Any]:
		return asdict(self)


@dataclass(frozen=True, slots=True)
class CommunicationPlan:
	"""Final structured output from the Communication Agent."""

	communication_goal: str
	recommended_action: str
	drafts: list[CommunicationDraft]
	follow_up_plan: str
	evidence_ids: list[str] = field(default_factory=list)
	risk_flags: list[str] = field(default_factory=list)
	confidence: float = 0.0
	agent_notes: list[str] = field(default_factory=list)

	def to_dict(self) -> dict[str, Any]:
		data = asdict(self)
		data["drafts"] = [item.to_dict() for item in self.drafts]
		return data

	@classmethod
	def from_dict(cls, data: dict[str, Any]) -> "CommunicationPlan":
		drafts = [
			CommunicationDraft(
				style=str(item.get("style") or ""),
				message=str(item.get("message") or ""),
				evidence_ids=[str(value) for value in item.get("evidence_ids", [])],
				why_this_works=str(item.get("why_this_works") or ""),
				risk_flags=[str(value) for value in item.get("risk_flags", [])],
			)
			for item in data.get("drafts", [])
			if isinstance(item, dict)
		]
		return cls(
			communication_goal=str(data.get("communication_goal") or "initial_outreach"),
			recommended_action=str(data.get("recommended_action") or "manual_review"),
			drafts=drafts,
			follow_up_plan=str(data.get("follow_up_plan") or ""),
			evidence_ids=[str(value) for value in data.get("evidence_ids", [])],
			risk_flags=[str(value) for value in data.get("risk_flags", [])],
			confidence=float(data.get("confidence") or 0.0),
			agent_notes=[str(value) for value in data.get("agent_notes", [])],
		)
