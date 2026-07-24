from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import textwrap
from typing import Any


def check_chroma_runtime(*, chroma_url: str | None = None, timeout_seconds: int = 30) -> dict[str, Any]:
	"""Run Chroma add/query in a child process.

	Some ChromaDB Windows wheels can terminate the interpreter with a native access
	violation during add/upsert. Running the smoke test out-of-process lets the CLI
	record progress and return a JSON error instead of losing state.
	"""

	chroma_url_literal = repr(chroma_url)
	code = textwrap.dedent(
		"""
		import json
		import tempfile
		import traceback
		from urllib.parse import urlparse

		try:
			import chromadb
			chroma_url = __CHROMA_URL__
			backend = "http" if chroma_url else "local"
			if chroma_url:
				parsed = urlparse(chroma_url if "://" in chroma_url else "http://" + chroma_url)
				host = parsed.hostname
				if not host:
					raise ValueError(f"Invalid ChromaDB URL: {{chroma_url}}")
				ssl = parsed.scheme == "https"
				port = parsed.port or (443 if ssl else 8000)
				client = chromadb.HttpClient(host=host, port=port, ssl=ssl)
			else:
				path = tempfile.mkdtemp(prefix="boss_chroma_smoke_")
				client = chromadb.PersistentClient(path=path)
			collection = client.get_or_create_collection(name="smoke", metadata={"hnsw:space": "cosine"})
			embedding = [0.0] * 384
			embedding[0] = 1.0
			collection.upsert(
				ids=["smoke-1"],
				documents=["boss-agent-cli chromadb smoke"],
				metadatas=[{"source": "smoke"}],
				embeddings=[embedding],
			)
			result = collection.query(query_embeddings=[embedding], n_results=1, include=["documents", "metadatas", "distances"])
			print(json.dumps({
				"ok": True,
				"version": chromadb.__version__,
				"backend": backend,
				"result_count": len(result.get("ids", [[]])[0]),
			}))
		except BaseException as exc:
			print(json.dumps({"ok": False, "error": repr(exc), "traceback": traceback.format_exc()}))
			raise
		"""
	).replace("__CHROMA_URL__", chroma_url_literal)
	try:
		result = subprocess.run(
			[sys.executable, "-X", "faulthandler", "-u", "-c", code],
			capture_output=True,
			text=True,
			timeout=timeout_seconds,
			stdin=subprocess.DEVNULL,
		)
	except subprocess.TimeoutExpired as exc:
		return {
			"ok": False,
			"error": "CHROMA_SMOKE_TIMEOUT",
			"stdout": exc.stdout or "",
			"stderr": exc.stderr or "",
		}
	payload = _last_json_line(result.stdout)
	if result.returncode == 0 and payload and payload.get("ok"):
		return {
			"ok": True,
			"version": payload.get("version"),
			"backend": payload.get("backend"),
			"result_count": payload.get("result_count", 0),
		}
	return {
		"ok": False,
		"error": "CHROMA_SMOKE_FAILED",
		"returncode": result.returncode,
		"payload": payload,
		"stdout": result.stdout,
		"stderr": result.stderr,
	}


def _last_json_line(text: str) -> dict[str, Any] | None:
	for line in reversed(text.splitlines()):
		line = line.strip()
		if not line:
			continue
		try:
			data = json.loads(line)
		except json.JSONDecodeError:
			continue
		if isinstance(data, dict):
			return data
	return None
