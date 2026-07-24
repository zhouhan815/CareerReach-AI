from boss_agent_cli.rag import chroma_health


class FakeCompletedProcess:
	returncode = 0
	stdout = '{"ok": true, "version": "test", "backend": "local", "result_count": 1}\n'
	stderr = ""


def test_check_chroma_runtime_uses_python_none_for_local_backend(monkeypatch):
	def fake_run(args, **kwargs):
		code = args[-1]
		assert "chroma_url = None" in code
		assert "chroma_url = null" not in code
		return FakeCompletedProcess()

	monkeypatch.setattr(chroma_health.subprocess, "run", fake_run)

	health = chroma_health.check_chroma_runtime()

	assert health["ok"] is True
	assert health["backend"] == "local"
