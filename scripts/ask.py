#!/usr/bin/env python3
"""Ask the knowledge system questions from a terminal.

    python scripts/ask.py                       # interactive prompt
    python scripts/ask.py "What is the 60-month auto loan APR?" "What was it as of May 2026? || 2026-05-31"

In the prompt: `question || 2026-05-31` answers as of that date; `/conflicts` lists the contradictions found;
`/asof 2026-05-31` sets a default date (`/asof` clears it); `/quit` exits. Snapshots load from ./snapshots
(unpacked from ./snapshots_zip on first use, like the scorer).
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "harness"))
sys.path.insert(0, str(ROOT / "submission"))

from run_eval import load_snapshots  # noqa: E402

from solution import build  # noqa: E402


def show(answer, seconds: float) -> None:
    flag = "" if answer.confident else "  [not confident]"
    print(f"\n{answer.text}{flag}")
    for s in answer.sources[:3]:
        print(f"  source: {s.url}" + (f"  ({s.snapshot_id})" if s.snapshot_id else ""))
    if answer.conflict_note:
        print(f"  note: {answer.conflict_note}")
    print(f"  ({seconds * 1000:.0f} ms)")


def ask(ks, line: str, default_as_of):
    question, as_of = line, default_as_of
    if "||" in line:
        question, as_of = (part.strip() for part in line.split("||", 1))
        as_of = as_of or None
    t = time.time()
    show(ks.answer(question, as_of=as_of), time.time() - t)


def main() -> None:
    snaps = load_snapshots(ROOT / "snapshots")
    if not snaps:
        sys.exit("No snapshots found. Put the five zips in snapshots_zip/ (or unpack them into snapshots/).")
    ks = build()
    t = time.time()
    for s in snaps:
        ks.ingest(s)
    print(f"Loaded {len(snaps)} snapshots ({snaps[0].taken_on} to {snaps[-1].taken_on}) in {time.time() - t:.1f}s.")
    if len(sys.argv) > 1:
        for line in sys.argv[1:]:
            print(f"\n> {line}")
            ask(ks, line, None)
        return
    print("Type a question. Add `|| YYYY-MM-DD` for an as-of date. /conflicts, /asof <date>, /quit.")
    default_as_of = None
    while True:
        try:
            line = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not line:
            continue
        if line in ("/quit", "/exit", "/q"):
            return
        if line.startswith("/asof"):
            default_as_of = line.split(maxsplit=1)[1].strip() if " " in line else None
            print(f"as_of = {default_as_of or 'latest'}")
            continue
        if line == "/conflicts":
            for c in ks.conflicts():
                print(f"- {c.topic}: {' vs '.join(c.values)} -> {c.resolution}\n    {c.reason}")
            continue
        ask(ks, line, default_as_of)


if __name__ == "__main__":
    main()
