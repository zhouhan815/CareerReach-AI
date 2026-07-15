#!/usr/bin/env sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
export PYTHONPATH="$ROOT/src"

python -m careerreach_ai \
  --backend "${1:-fixture}" \
  --input "$ROOT/examples/mock_opportunity.json" \
  --output "$ROOT/examples/mock_agent_output.json" \
  --pretty
