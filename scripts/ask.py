#!/usr/bin/env python3
"""Ask the knowledge system questions from a terminal.

    python scripts/ask.py                                   # interactive prompt
    python scripts/ask.py "What is the 60-month auto loan APR?"
    python scripts/ask.py --as-of 2026-05-31 "What is the 12-month certificate APY?"
    python scripts/ask.py --conflicts                       # print the contradictions found

Snapshots load from ./snapshots (unpacked from ./snapshots_zip on first use, exactly like the scorer).
"""
import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "harness"))
sys.path.insert(0, str(ROOT / "submission"))

from run_eval import load_snapshots  # noqa: E402

from solution import build  # noqa: E402

PROMPT_HELP = "Type a question. Commands: /asof YYYY-MM-DD (answer as of that date; /asof alone resets), /conflicts, /quit."


def load():
    snaps = load_snapshots(ROOT / "snapshots")
    if not snaps:
        sys.exit("No snapshots found. Put the five zips in snapshots_zip/ (or unpack them into snapshots/).")
    ks = build()
    started = time.time()
    for s in snaps:
        ks.ingest(s)
    print(f"Loaded {len(snaps)} snapshots ({snaps[0].taken_on} to {snaps[-1].taken_on}) in {time.time() - started:.1f}s.")
    return ks


def show(answer, seconds: float) -> None:
    flag = "" if answer.confident else "  [not confident]"
    print(f"\n{answer.text}{flag}")
    for s in answer.sources[:3]:
        print(f"  source: {s.url}" + (f"  ({s.snapshot_id})" if s.snapshot_id else ""))
    if answer.conflict_note:
        print(f"  note: {answer.conflict_note}")
    print(f"  ({seconds * 1000:.0f} ms)")


def print_conflicts(ks) -> None:
    for c in ks.conflicts():
        print(f"- {c.topic}: {' vs '.join(c.values)} -> {c.resolution}\n    {c.reason}")


def interactive(ks) -> None:
    print(PROMPT_HELP)
    as_of = None
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
            as_of = line.split(maxsplit=1)[1].strip() if " " in line else None
            print(f"as_of = {as_of or 'latest'}")
        elif line == "/conflicts":
            print_conflicts(ks)
        else:
            started = time.time()
            show(ks.answer(line, as_of=as_of), time.time() - started)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ask the knowledge system questions.")
    parser.add_argument("questions", nargs="*", help="questions to answer; none starts an interactive prompt")
    parser.add_argument("--as-of", metavar="YYYY-MM-DD", help="answer as the website stood on this date")
    parser.add_argument("--conflicts", action="store_true", help="print the contradictions found and exit")
    args = parser.parse_args()
    ks = load()
    if args.conflicts:
        print_conflicts(ks)
        return
    if not args.questions:
        interactive(ks)
        return
    for question in args.questions:
        print(f"\n> {question}" + (f"  (as of {args.as_of})" if args.as_of else ""))
        started = time.time()
        show(ks.answer(question, as_of=args.as_of), time.time() - started)


if __name__ == "__main__":
    main()
