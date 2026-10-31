# NOTES

## What this is

`submission/solution.py` builds a knowledge system over five crawls of a credit union's website. It answers
member questions with the current value, says so when the site does not say, and lists where the site
contradicts itself. The core is deterministic Python with no third-party dependency. One optional, small
Anthropic call helps parse questions the rules cannot place.

## How ingest works

Each snapshot is parsed into three stores. Ingest for five snapshots (about 3,300 pages) takes about 11 seconds.

1. **Facts from tables.** Every markdown rate table becomes one fact per numeric cell. A fact records the
   product, its tier (balance range, loan amount range, model-year range), the term, the metric (APY,
   dividend rate, rate, APR), the value, the page, and the "Rates are effective as of" date printed under
   the table. The product name comes from the label line above the table; older pages that omit the
   product column get the name of the authoritative table with the same balance tiers.
2. **Facts from prose.** Regexes pull counts (branches, employees, members, assets), the routing number,
   branch hours blocks, street addresses, closing dates, Forbes ordinals, "Label: value" lines, rate
   sentences, and fee-schedule lines.
3. **Chunks.** Section-sized text chunks go into a BM25 index. Navigation and footer lines that repeat
   across many pages are dropped first. Identical chunks across snapshots are stored once with the list
   of snapshots and URLs they appear in.

Each page gets an authority class from its URL: rate sheets (100) > product pages (90) > contact and
about pages (85) > newsroom (60) > blog (50) > promo landing pages (40) > calculators and legal pages (30)
> files (20). A table that does not match its page (an auto table on the checking page) loses 40 points.
A page missing from a crawl stays known from the newest earlier crawl, at 10 points less.

## How "current" is decided

Authority only matters when two sources disagree on the same fact. The order is:

1. Higher authority class wins. The rate sheet beats a calculator or a promo page.
2. Newer "effective as of" date wins.
3. For prose facts, the newer article date wins. The branch count comes from the newest press release that
   states one, so "22 branch office locations" beats older releases that say 23 or 24.
4. Newer crawl wins.

A page is not stale because it is old. The Hy-Vee closing date comes from a 2025 release that nothing
newer contradicts.

Absence from the authoritative source is a signal too. If the rate sheet covers a product family but a product
or tier appears only on promo landing pages, calculators or files, the system treats the offer as ended: it
refuses with a "the current rate sheet doesn't list it" message and keeps the leftover value in
`conflict_note`. For the same reason, vanished promo and calculator pages are not carried forward; vanished
informational pages (the fee schedule, the contact page) are.

## How a question is answered

1. A rule-based parser turns the question into a structured query: intent, product family, product name,
   term, model year, balance or loan amount, metric, and qualifiers such as jumbo, special, Roth, business.
   Synonyms are normalised ("CD" is a certificate, "car" is auto, "five-year" is 60 months).
2. The snapshot is the newest one taken on or before `as_of`. Without `as_of`, it is the latest crawl.
   If the question itself says "as of May 2026", that date is used.
3. The facts for that snapshot are filtered by the query. A model year matches a tier by range, so 2025
   matches "2024-27 Model Year". When several pages give different values for the same tier, the authority
   order above picks one and the others go into `conflict_note`.
4. The answer text is built from templates. It states one value per fact. An `as_of` answer never mentions
   values from other dates. If the question gives no tier, every tier is listed with its own value.
5. Free-text questions (eligibility, how-to, descriptions) use BM25 retrieval and return one or two
   sentences from the best chunk, never the whole chunk. A sentence that quotes a rate the current rate
   tables do not contain is dropped.
6. The system refuses when the product exists but the requested figure does not (a 7/1 ARM rate, a
   construction-loan rate, hours for a branch with no hours on the site, a fee the schedule does not list).
   Refusals contain no numbers and set `confident=False`. A product that an earlier crawl listed but the
   current one does not gets a "no longer lists" refusal, with the last value in `conflict_note`.
7. "Minimum to open" and "minimum balance to earn" questions read the matching table columns. Fee questions
   check the fee schedule first and fall back to the product page text ("no monthly service charges").
8. If `as_of` is earlier than the first crawl, the answer comes from the earliest crawl and says so.
9. Answers are cached by normalised question and `as_of`, so repeated questions return the same text.

## How conflicts are found

`conflicts()` groups facts by product, tier, term and metric. Two kinds of entries come out:

- Within the latest crawl, the same fact has different values on different pages. Example: the rate page
  shows the 60-month auto APR as 5.39% while a promo page still shows 5.34%.
- Across crawls, the authoritative value changed. Example: the 12-month certificate APY moved from 2.90%
  to 3.40%.

Sibling tiers that went stale together are one entry. Each entry names the winning value and the reason.

## API keys

None are required, and nothing in this repository contains one. The default run is fully offline and
deterministic, and that is the configuration to grade.

An optional LLM question parser exists as an experiment. It is off unless both `KS_USE_LLM=1` and
`ANTHROPIC_API_KEY` are set in the environment of the process running the scorer (for example
`KS_USE_LLM=1 ANTHROPIC_API_KEY=... python harness/run_eval.py ...`). When on, the system makes one call to
`claude-haiku-5-5` for a question the rules cannot classify. The call returns a structured query only; it never
sees website text and never writes answer text. Each call has a 3-second cap and any error falls back to the
rules. `KS_LLM_MODEL` changes the model. Measured on the practice set the parser changes no answers and adds
about 0.8 seconds at p95, which is why it is opt-in: the kit's own `--judge` option reads the same key variable,
and a graded run should not pick up a paid network dependency by accident. It did help on phrasings the rules
cannot place ("rate on a used pickup from 2019, 5 year loan"), so it stays available.

## Results

| Set | Score |
| --- | --- |
| Practice set (40 questions, `eval/public_eval.jsonl`) | 0.969; the one miss has an empty `must_include` list and needs the LLM judge |
| Harness self-test fixture (synthetic site, conflicts gold) | 1.0 |
| Extra paraphrase, as-of, change and fee set (35 questions, `eval/extra_eval.jsonl`) | 1.0 |

The extra set was written from reading the snapshots, before the system handled those cases, and is used as a
regression set. `scripts/check.sh` runs lint, the unit tests, the self-test and both question sets.

## Code quality

- `ruff check submission tests` passes with the rule set in `pyproject.toml`.
- 67 tests on synthetic fixtures cover table parsing, prose extraction, the query parser, the store and index,
  conflicts, the LLM merge (stubbed client), every answer handler, and two-snapshot end-to-end flows. Line
  coverage is 90%.
- CI runs lint, tests and the harness self-test on Python 3.9, 3.11 and 3.12.
- `answer()` and `conflicts()` never raise: a handler bug is logged and turns into a digit-free refusal or an
  empty list.

## What is and is not site-specific

The institution's name is read from page titles, and the parsers take it as a parameter rather than matching it.
The product vocabulary (product aliases, link targets, promo paths), the US state list used for the charter area,
the online-banking wording in the account how-to answer, and the regexes for counts in press-release boilerplate
are tuned to this website. Pointing the system at another credit union would mean revisiting those tables; the
fact model, authority rules, snapshot history and retrieval would carry over unchanged.

## Limits

- Branch hours exist only in press releases about branch openings, so the general lobby-hours answer lists
  the common schedules and asks which branch.
- The fee handler needs every content word of the question to appear in a fee-schedule label. A question
  about a fee the schedule words differently gets a refusal rather than a guess.
- Free-text answers are extractive. They quote the site; they do not summarise it.
