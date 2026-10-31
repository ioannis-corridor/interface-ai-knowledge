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

## Quality checks

```bash
pip install pytest ruff
ruff check submission tests        # lint, config in pyproject.toml
python -m pytest                   # 53 unit and end-to-end tests on synthetic fixtures (89% line coverage)
python harness/run_eval.py --submission submission --snapshots harness/selftest/snapshots \
    --eval harness/selftest/eval.jsonl --conflicts-gold harness/selftest/conflicts_gold.json
```

The GitHub Actions workflow in `.github/workflows/ci.yml` runs all three on Python 3.9, 3.11 and 3.12. The real
snapshots are not available in CI, so the scorer there uses the harness's own synthetic self-test site.

## Code map

```
submission/solution.py        build() -> KnowledgeSystem
submission/ks/system.py       ingest / answer / conflicts; caching; the harness contract boundary
submission/ks/tables.py       markdown rate tables -> Facts
submission/ks/entities.py     prose facts: counts, hours, addresses, closures, fees, "Label: value" lines
submission/ks/pages.py        page authority classes, article dates, boilerplate filter
submission/ks/store.py        facts per snapshot, as_of selection, carry-forward of vanished pages
submission/ks/index.py        section chunks + BM25 scoped to a snapshot
submission/ks/query.py        question -> structured Query (rules); strict merge of the optional LLM parse
submission/ks/llm.py          optional Anthropic parser (structured output only)
submission/ks/answer/         composer: entity, facts, fees, retrieval handlers; Draft and refusal templates
submission/ks/conflicts.py    contradictions within the latest crawl and across crawls
submission/ks/format.py       shared wording helpers
```
