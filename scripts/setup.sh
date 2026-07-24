#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e "./third_party/boss-agent-cli[rag,communication]"
.venv/bin/python -m pip install -e ".[dev]"

mkdir -p .data

echo "CareerReach AI is ready."
echo "Activate: source .venv/bin/activate"
echo "Demo: careerreach-ai --backend fixture --input examples/mock_opportunity.json --pretty"
