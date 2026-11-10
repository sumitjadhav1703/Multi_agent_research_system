#!/usr/bin/env bash
# Offline ResearchMind matrix. Uses the mock provider only.
# Does not run the DeepEval judge and does not read .env.
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ -n "${DATABASE_URL:-}" ]]; then
  echo "Refusing to run: DATABASE_URL is set. Unset it so this matrix stays on local SQLite." >&2
  exit 2
fi

export USE_MOCK_PROVIDER=true
export DATABASE_URL=
export QUEUE_CONSUMER_ENABLED=false
export TURNSTILE_SECRET_KEY=
export PYTHONPATH=.
unset RM_EVAL_JUDGE || true

if [[ -n "${PYTHON:-}" ]]; then
  PY="$PYTHON"
elif [[ -x /tmp/rm_v2_venv/bin/python ]]; then
  PY=/tmp/rm_v2_venv/bin/python
else
  PY=python3
fi

V1_PY="${V1_PYTHON:-}"
if [[ -z "$V1_PY" ]]; then
  for candidate in /tmp/rm_v1_venv/bin/python /tmp/rm_phase12_venv/bin/python "$PY"; do
    if [[ -x "$candidate" ]] && "$candidate" -c "import streamlit, groq, bs4" >/dev/null 2>&1; then
      V1_PY="$candidate"
      break
    fi
  done
fi
if [[ -z "$V1_PY" ]]; then
  echo "V1 suite needs v1/requirements.txt (streamlit, groq, bs4). Set V1_PYTHON." >&2
  exit 2
fi

echo "== V1 v1/tests/ ($V1_PY) =="
(cd v1 && "$V1_PY" -m unittest discover -s tests -q)

echo "== V2 backend/tests/ ($PY) =="
"$PY" -m unittest discover -s backend/tests -q

echo "== evals/tests/ =="
"$PY" -m unittest discover -s evals/tests -q

echo "== evals deterministic fixture check =="
"$PY" -m evals.cli deterministic

if [[ "${RUN_NODE_SUITES:-}" == "1" ]]; then
  echo "== frontend lint, typecheck, vitest, build =="
  (cd frontend && npm run lint && npm run typecheck && npm test && npm run build)
  echo "== mcp-server vitest =="
  (cd mcp-server && npm test)
fi

echo "Offline Python matrix finished. The LLM judge was not run."
