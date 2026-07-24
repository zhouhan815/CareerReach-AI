from __future__ import annotations

import json
from pathlib import Path

from careerreach_ai.boss_cli import build_boss_command
from careerreach_ai.contracts import validate_agent_output
from careerreach_ai.fixture_agent import build_fixture_output
from careerreach_ai.redaction import find_sensitive_markers


ROOT = Path(__file__).resolve().parents[1]


def load_seed() -> dict:
	return json.loads((ROOT / "examples" / "mock_opportunity.json").read_text(encoding="utf-8"))


def test_fixture_output_matches_agent_contract() -> None:
	payload = build_fixture_output(load_seed())

	assert validate_agent_output(payload) == []
	assert payload["data"]["plan"]["recommended_action"] == "send"
	assert payload["data"]["plan"]["evidence_ids"] == ["company:demo", "job:demo", "resume:demo"]
	assert payload["data"]["runtime"]["orchestrator"] == "fixture_contract"
	assert "supervisor" not in json.dumps(payload, ensure_ascii=False).lower()


def test_boss_backend_command_uses_safe_defaults() -> None:
	command = build_boss_command(load_seed())

	assert command[:5] == ["boss", "--json", "ai", "communication", "plan"]
	assert "--mode" in command
	assert "rules" in command
	assert "--no-rag" in command
	assert "--no-save" in command
	assert "--context" in command


def test_public_examples_do_not_include_sensitive_markers() -> None:
	seed = load_seed()
	payload = build_fixture_output(seed)

	assert find_sensitive_markers(seed) == []
	assert find_sensitive_markers(payload) == []
