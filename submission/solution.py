"""
Submission entry point. `build()` returns the KnowledgeSystem the harness drives.

How it works (short version; see NOTES.md):
  ingest   - parse every markdown rate table into Facts (product, tier, term, metric, value, effective date),
             pull prose facts with regexes (counts, routing number, hours, addresses, closures), classify each
             page's authority, and index section chunks for BM25 retrieval. History is kept per snapshot.
  answer   - parse the question into a structured query (rules, optionally refined by a small LLM call), pick the
             snapshot for `as_of`, look the fact up, resolve disagreeing copies by authority and effective date,
             and compose a one-value answer. Refuse (without numbers) when the site doesn't say.
  conflicts- same fact key, different values: within the latest snapshot and across snapshots.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
_kit_root = next((d for d in HERE.parents if (d / "harness" / "contract.py").exists()), None)
if _kit_root is not None:
    sys.path.insert(0, str(_kit_root / "harness"))

import contract  # noqa: E402  (the harness's own dataclasses, so our objects are its Answer/Conflict/Source)

from ks.system import KnowledgeSystem  # noqa: E402


def build():
    return KnowledgeSystem(contract)
