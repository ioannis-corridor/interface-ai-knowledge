#!/usr/bin/env bash
# Everything a reviewer can run without the API key: lint, unit tests, the harness self-test, and (when the
# snapshot zips are present in snapshots_zip/) the practice set and the extra paraphrase set.
set -euo pipefail
cd "$(dirname "$0")/.."
export KS_DISABLE_LLM=1
PY="${PYTHON:-$(command -v python3 || command -v python)}"
"$PY" -m ruff check submission tests
"$PY" -m pytest
"$PY" harness/run_eval.py --submission submission --snapshots harness/selftest/snapshots \
    --eval harness/selftest/eval.jsonl --conflicts-gold harness/selftest/conflicts_gold.json --out results/selftest
if ls snapshots_zip/*.zip >/dev/null 2>&1 || ls snapshots/0*/manifest.json >/dev/null 2>&1; then
  "$PY" harness/run_eval.py --submission submission --eval eval/public_eval.jsonl --out results/public
  "$PY" harness/run_eval.py --submission submission --eval eval/extra_eval.jsonl --out results/extra --repeat-sample 0
else
  echo "snapshots not present: skipped the practice and extra sets (drop the five zips into snapshots_zip/)"
fi
