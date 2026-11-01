#!/usr/bin/env bash
# Everything a reviewer can run without the API key: lint, unit tests, the harness self-test, and (when the
# snapshot zips and the git-ignored question sets are present, per eval/README.md) the practice set and the
# extra paraphrase set.
set -euo pipefail
cd "$(dirname "$0")/.."
unset KS_USE_LLM   # the offline path is the graded path
PY="${PYTHON:-$(command -v python3 || command -v python)}"
"$PY" -m ruff check submission tests scripts
"$PY" -m pytest
"$PY" harness/run_eval.py --submission submission --snapshots harness/selftest/snapshots \
    --eval harness/selftest/eval.jsonl --conflicts-gold harness/selftest/conflicts_gold.json --out results/selftest
if ls snapshots_zip/*.zip >/dev/null 2>&1 || ls snapshots/0*/manifest.json >/dev/null 2>&1; then
  if [ -f eval/public_eval.jsonl ]; then
    "$PY" harness/run_eval.py --submission submission --eval eval/public_eval.jsonl --out results/public
  else
    echo "eval/public_eval.jsonl not present: skipped the practice set (copy it from the kit, per eval/README.md)"
  fi
  if [ -f eval/extra_eval.jsonl ]; then
    "$PY" harness/run_eval.py --submission submission --eval eval/extra_eval.jsonl --out results/extra --repeat-sample 0
  else
    echo "eval/extra_eval.jsonl not present: skipped the extra set (see eval/README.md)"
  fi
else
  echo "snapshots not present: skipped the practice and extra sets (drop the five zips into snapshots_zip/)"
fi
