# Knowledge system that knows what's true now

A build assignment: answer credit-union members' questions from five website crawls that contradict each
other. Give the current value, cite the page, resolve conflicts, and say "I don't know" when the site does
not say. [`NOTES.md`](NOTES.md) explains the approach.

## Layout

```
submission/          the solution (solution.py with build(), package ks/)
harness/             the organisers' scorer, unchanged
eval/                the 40 practice questions, unchanged
starter/             the organisers' naive baseline, unchanged
tests/               unit tests on synthetic fixtures
docs/                plan and kit README
snapshots/           website crawls go here (not committed)
```

The website snapshots are not in this repository. Put the five zips in `snapshots_zip/`, or unzip them into
`snapshots/`, before you run the scorer.

## Run

Python 3.9 or newer. The core has no dependencies; `requirements.txt` adds the optional Anthropic parser.

```bash
pip install -r requirements.txt
python harness/run_eval.py --submission submission --eval eval/public_eval.jsonl
```

To turn the optional LLM parser on, set `ANTHROPIC_API_KEY`. Without it, the rule-based parser handles
every question.

Unit tests and the harness self-test:

```bash
python -m pytest -q tests
python harness/run_eval.py --submission submission --snapshots harness/selftest/snapshots \
    --eval harness/selftest/eval.jsonl --conflicts-gold harness/selftest/conflicts_gold.json
```
