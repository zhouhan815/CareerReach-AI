from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from boss_agent_cli.rag.embeddings import HashEmbeddingProvider
from boss_agent_cli.rag.models import RagChunk, RagSearchResult


class RagDependencyError(RuntimeError):
	"""Raised when an optional RAG dependency is not installed."""


def _load_chromadb() -> Any:
	try:
		import chromadb
	except ModuleNotFoundError as exc:
		raise RagDependencyError("chromadb is required for RAG storage") from exc
	return chromadb


class ChromaRagStore:
	"""Persistent ChromaDB-backed RAG store."""

	def __init__(
		self,
		data_dir: Path,
		*,
		collection_name: str = "career_rag",
		chroma_url: str | None = None,
		embedding_provider: HashEmbeddingProvider | None = None,
	) -> None:
		chromadb = _load_chromadb()
		self.persist_dir = data_dir / "rag" / "chroma"
		self.persist_dir.mkdir(parents=True, exist_ok=True)
		self.collection_name = collection_name
		self.chroma_url = chroma_url
		self.backend = "http" if chroma_url else "local"
		self.embedding_provider = embedding_provider or HashEmbeddingProvider()
		if chroma_url:
			host, port, ssl = _parse_chroma_url(chroma_url)
			self._client = chromadb.HttpClient(host=host, port=port, ssl=ssl)
		else:
			self._client = chromadb.PersistentClient(path=str(self.persist_dir))
		self._collection = self._client.get_or_create_collection(
			name=collection_name,
			metadata={"hnsw:space": "cosine"},
		)

	def reset_collection(self) -> None:
		try:
			self._client.delete_collection(self.collection_name)
		except Exception:
			pass
		self._collection = self._client.get_or_create_collection(
			name=self.collection_name,
			metadata={"hnsw:space": "cosine"},
		)

	def count(self) -> int:
		return int(self._collection.count())

	def delete_where(self, where: dict[str, Any]) -> None:
		self._collection.delete(where=where)

	def upsert_chunks(self, chunks: list[RagChunk]) -> int:
		if not chunks:
			return 0
		ids = [chunk.chunk_id for chunk in chunks]
		documents = [chunk.text for chunk in chunks]
		metadatas = [_sanitize_metadata(chunk.metadata) for chunk in chunks]
		embeddings = self.embedding_provider.embed_documents(documents)
		self._collection.upsert(
			ids=ids,
			documents=documents,
			metadatas=metadatas,
			embeddings=embeddings,
		)
		return len(chunks)

	def search(
		self,
		query: str,
		*,
		top_k: int = 5,
		where: dict[str, Any] | None = None,
	) -> list[RagSearchResult]:
		query_embedding = self.embedding_provider.embed_text(query)
		result = self._collection.query(
			query_embeddings=[query_embedding],
			n_results=max(1, top_k),
			where=where,
			include=["documents", "metadatas", "distances"],
		)
		ids = result.get("ids", [[]])[0]
		documents = result.get("documents", [[]])[0]
		metadatas = result.get("metadatas", [[]])[0]
		distances = result.get("distances", [[]])[0]
		items: list[RagSearchResult] = []
		for index, chunk_id in enumerate(ids):
			distance = float(distances[index]) if index < len(distances) and distances[index] is not None else None
			score = (1.0 - distance) if distance is not None else None
			items.append(
				RagSearchResult(
					chunk_id=str(chunk_id),
					text=str(documents[index]) if index < len(documents) else "",
					metadata=dict(metadatas[index] or {}) if index < len(metadatas) else {},
					distance=distance,
					score=score,
				)
			)
		return items


def _sanitize_metadata(metadata: dict[str, Any]) -> dict[str, str | int | float | bool]:
	clean: dict[str, str | int | float | bool] = {}
	for key, value in metadata.items():
		if value is None:
			continue
		if isinstance(value, (str, int, float, bool)):
			clean[key] = value
		else:
			clean[key] = json.dumps(value, ensure_ascii=False, sort_keys=True)
	return clean


def _parse_chroma_url(url: str) -> tuple[str, int, bool]:
	parsed = urlparse(url if "://" in url else f"http://{url}")
	host = parsed.hostname
	if not host:
		raise ValueError(f"Invalid ChromaDB URL: {url}")
	ssl = parsed.scheme == "https"
	port = parsed.port or (443 if ssl else 8000)
	return host, port, ssl
