from __future__ import annotations

import hashlib
import math
import re

_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]+|[a-zA-Z0-9][a-zA-Z0-9_+#./-]*")


class HashEmbeddingProvider:
	"""Deterministic local embeddings for zero-network RAG bootstrap.

	This is intentionally simple and replaceable. It lets ChromaDB store and query
	career context without downloading a model or calling an external embeddings API.
	"""

	def __init__(self, dimension: int = 384) -> None:
		if dimension <= 0:
			raise ValueError("dimension must be positive")
		self.dimension = dimension

	def embed_documents(self, texts: list[str]) -> list[list[float]]:
		return [self.embed_text(text) for text in texts]

	def embed_text(self, text: str) -> list[float]:
		vector = [0.0] * self.dimension
		for token in self._tokens(text):
			digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
			value = int.from_bytes(digest, "big", signed=False)
			index = value % self.dimension
			sign = 1.0 if value & (1 << 63) else -1.0
			vector[index] += sign
		norm = math.sqrt(sum(value * value for value in vector))
		if norm == 0:
			return vector
		return [value / norm for value in vector]

	@staticmethod
	def _tokens(text: str) -> list[str]:
		tokens: list[str] = []
		for match in _TOKEN_RE.finditer(text.lower()):
			token = match.group(0).strip()
			if not token:
				continue
			if re.fullmatch(r"[\u4e00-\u9fff]+", token):
				tokens.extend(token)
				tokens.extend(token[index:index + 2] for index in range(max(0, len(token) - 1)))
			else:
				tokens.append(token)
		return tokens
