from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class RagChunk:
	"""A single retrievable context chunk with traceable metadata."""

	chunk_id: str
	text: str
	metadata: dict[str, Any] = field(default_factory=dict)

	def to_dict(self) -> dict[str, Any]:
		return asdict(self)


@dataclass(frozen=True, slots=True)
class RagSearchResult:
	chunk_id: str
	text: str
	metadata: dict[str, Any]
	distance: float | None = None
	score: float | None = None

	def to_dict(self) -> dict[str, Any]:
		return asdict(self)
