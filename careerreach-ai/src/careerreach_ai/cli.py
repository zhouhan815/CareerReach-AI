from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from careerreach_ai.boss_cli import BossCliError, run_boss_communication_plan
from careerreach_ai.contracts import validate_agent_output
from careerreach_ai.fixture_agent import build_fixture_output


def main(argv: Sequence[str] | None = None) -> int:
	parser = argparse.ArgumentParser(description="Run the CareerReach AI demo.")
	parser.add_argument("--input", type=Path, default=Path("examples/mock_opportunity.json"))
	parser.add_argument("--output", type=Path)
	parser.add_argument("--backend", choices=("fixture", "boss"), default="fixture")
	parser.add_argument("--boss-executable", default="boss")
	parser.add_argument("--data-dir", type=Path)
	parser.add_argument("--mode", choices=("rules", "auto", "ai"), default="rules")
	parser.add_argument("--use-rag", action="store_true")
	parser.add_argument("--save", action="store_true")
	parser.add_argument("--pretty", action="store_true")
	args = parser.parse_args(argv)

	seed = _load_json(args.input)
	try:
		if args.backend == "boss":
			payload = run_boss_communication_plan(
				seed,
				executable=args.boss_executable,
				mode=args.mode,
				use_rag=args.use_rag,
				save=args.save,
				data_dir=args.data_dir,
			)
		else:
			payload = build_fixture_output(seed)
	except BossCliError as exc:
		print(f"backend_error: {exc}", file=sys.stderr)
		return 2

	issues = validate_agent_output(payload)
	if issues:
		for issue in issues:
			print(f"contract_warning: {issue}", file=sys.stderr)

	text = json.dumps(payload, ensure_ascii=False, indent=2 if args.pretty else None)
	if args.output:
		args.output.parent.mkdir(parents=True, exist_ok=True)
		args.output.write_text(text + "\n", encoding="utf-8")
	print(text)
	return 0 if not any(issue.startswith("error:") for issue in issues) else 3


def _load_json(path: Path) -> dict[str, Any]:
	try:
		value = json.loads(path.read_text(encoding="utf-8"))
	except FileNotFoundError as exc:
		raise SystemExit(f"Input file not found: {path}") from exc
	if not isinstance(value, dict):
		raise SystemExit("Input JSON must be an object.")
	return value
