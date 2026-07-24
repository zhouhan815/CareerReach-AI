from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from boss_agent_cli.communication.models import EvidenceItem, OpportunitySeed
from boss_agent_cli.rag.models import RagSearchResult
from boss_agent_cli.rag.store import ChromaRagStore


class CommunicationRetriever:
	"""Retriever facade that keeps Communication Agent evidence scoped and traceable."""

	def __init__(self, store: ChromaRagStore, *, top_k: int = 8) -> None:
		self._store = store
		self._top_k = top_k

	def retrieve(self, seed: OpportunitySeed) -> list[EvidenceItem]:
		query = _query_for_seed(seed)
		queries: list[tuple[str, dict[str, Any] | None]] = []
		if seed.company:
			queries.append((query, {"company": seed.company}))
		if seed.job_id:
			queries.append((query, {"job_id": seed.job_id}))
		if not queries:
			queries.append((query, None))

		seen: set[str] = set()
		evidence: list[EvidenceItem] = []
		playbook_filter = {"$and": [{"doc_type": "message_template"}, {"source": "outreach_playbook"}]}
		for result in self._store.search(_playbook_query_for_seed(seed), top_k=min(2, self._top_k), where=playbook_filter):
			_append_unique_evidence(evidence, seen, result)

		resume_filter = {"doc_type": "resume"}
		for result in self._store.search(_resume_query_for_seed(seed), top_k=min(3, self._top_k), where=resume_filter):
			_append_unique_evidence(evidence, seen, result)

		for item_query, where in queries:
			for result in self._store.search(item_query, top_k=self._top_k, where=where):
				_append_unique_evidence(evidence, seen, result)
				if len(evidence) >= self._top_k:
					return evidence
		return evidence


def build_communication_retriever(
	data_dir: Path,
	*,
	collection_name: str = "career_rag",
	chroma_url: str | None = None,
	top_k: int = 8,
) -> CommunicationRetriever:
	store = ChromaRagStore(data_dir, collection_name=collection_name, chroma_url=chroma_url)
	return CommunicationRetriever(store, top_k=top_k)


def evidence_from_rag_result(result: RagSearchResult) -> EvidenceItem:
	metadata = result.metadata
	return EvidenceItem(
		evidence_id=result.chunk_id,
		text=result.text,
		source=str(metadata.get("source") or ""),
		doc_type=str(metadata.get("doc_type") or ""),
		chunk_kind=str(metadata.get("chunk_kind") or ""),
		company=str(metadata.get("company") or ""),
		job_title=str(metadata.get("job_title") or ""),
		job_id=str(metadata.get("job_id") or ""),
		score=result.score,
	)


def evidence_from_text(text: str, *, prefix: str = "direct") -> EvidenceItem:
	digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]
	return EvidenceItem(evidence_id=f"{prefix}:{digest}", text=text, source="direct_input")


def _append_unique_evidence(evidence: list[EvidenceItem], seen: set[str], result: RagSearchResult) -> None:
	if result.chunk_id in seen:
		return
	seen.add(result.chunk_id)
	evidence.append(evidence_from_rag_result(result))


def _query_for_seed(seed: OpportunitySeed) -> str:
	parts = [
		seed.company,
		seed.job_title,
		seed.goal,
		seed.latest_message,
		str(seed.facts.get("company_business") or ""),
		str(seed.facts.get("job_requirement_judgment") or ""),
	]
	return " ".join(part for part in parts if part).strip() or "communication plan"


def _playbook_query_for_seed(seed: OpportunitySeed) -> str:
	return f"{_query_for_seed(seed)} CareerReach outreach playbook greeting template"


def _resume_query_for_seed(seed: OpportunitySeed) -> str:
	return f"{_query_for_seed(seed)} resume experience project skills evidence"
