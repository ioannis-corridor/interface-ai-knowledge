# Design notes

How the scorer shaped the design, what the data looks like, and which alternatives were set aside.
[`../NOTES.md`](../NOTES.md) describes the system as built.

## 1. What the scorer rewards

Read from `harness/scoring.py` before any code was written.

| Rule in the scorer | Design consequence |
| --- | --- |
| `must_include` / `must_not_include` match **by numeric value**. One trap value anywhere in the text zeroes the item. | State one value, the right one. Never list other tiers or old values unless the question asks for a list. |
| `should_refuse` passes only if the answer declines **and** contains no number that is not in the question. | Refusals are templates with no digits; the final validator enforces it. |
| Source credit is a path-level URL match. | Cite the authoritative page; fragments and query strings do not matter. |
| Consistency compares the **set of numbers** across paraphrases and repeat calls, multiplied by accuracy. | Deterministic pipeline, stable tie-breaks, answers cached by normalised question. |
| Speed wants p95 at or below 2 s; zero at 20 s. | Everything in memory. The optional LLM call runs only for questions the rules cannot place. |
| Conflicts is F1 against a gold list; each gold entry matches one submission. | One entry per fact key, sibling tiers merged, values formatted like the site. |

Many `must_not_include` values do not exist anywhere in the snapshots. They are hallucinations a previous assistant
produced. A system that only speaks from extracted facts wins those for free.

## 2. What the data looks like

- 637 to 705 pages per crawl, about 5 MB of markdown each. Small enough for plain Python in memory.
- Byte-level diffs are noise: 615 of 633 shared pages "changed" between the first two crawls because of
  navigation and footer text. Change detection has to run on extracted facts.
- Two master rate sheets hold every rate. The same tables are repeated on product pages, calculators and promo
  landing pages, and the copies go stale at different times. Every table ends with "Rates are effective as of
  MM/DD/YYYY", a recency signal that beats crawl date.
- Table product labels are plain text lines above the table, not headings. Older pages drop the product column.
- Tier labels drift between crawls (`2023-26 Model Year` becomes `2024-27 Model Year`), so a model year has to
  match a tier by range, not by label.
- Branch hours exist only in press releases about branch openings. Counts such as the number of branches appear
  in the boilerplate paragraph of every release, and the figure changes over the years.
- A product can appear mid-series (a 17-month certificate special first shows up in the third crawl) or vanish.

## 3. Architecture

A deterministic fact layer plus BM25 retrieval, with an optional LLM that only parses questions.

```
ingest(snapshot)                     answer(question, as_of)                  conflicts()
  tables  -> Facts                     rules parser -> Query                     group facts by key
  prose   -> Facts (regex)             (optional LLM fills gaps)                 within latest crawl: differing
  pages   -> authority class           pick snapshot for as_of                     values on different pages
  chunks  -> BM25 index                facts -> resolve by authority,            across crawls: value moved
  facts per snapshot (history)           effective date, article date           merge sibling tiers; one entry
                                       templates / sentence extraction            per fact key
                                       validator: plain text, digit-free
                                         refusals, one value per fact
```

Authority classes decide only when two sources disagree on the same fact: rate sheet (100) > product page (90) >
contact and about pages (85) > newsroom (60) > blog (50) > promo landing page (40) > calculator and legal pages
(30) > files (20). A table that does not match its page (an auto table on the checking page) loses 40 points. A
page missing from a crawl is served from the newest earlier crawl at 10 points less.

## 4. Alternatives considered

| Alternative | Why not |
| --- | --- |
| LLM generates the answer text from retrieved chunks | The scorer zeroes exactly what generation does by default: both values, hedges, extra figures. The fact layer is still needed to know which chunk is stale. |
| LLM extracts facts at ingest (ingest is untimed) | The tables are already structured; deterministic parsing is more reliable, costs nothing in the grader's run, and keeps the knowledge base deterministic. |
| Embeddings for retrieval | BM25 plus a URL-slug boost covered the free-text questions in the practice and private sets. A vector index adds a dependency and a key at ingest. |
| LLM parser as the primary router | Measured: letting the LLM override the rules cut the practice score from 0.969 to 0.853 because it relabels as-of questions as change questions. Strict gap filling keeps the score and helps on phrasings the rules miss. |
| Precomputed knowledge base in the repo | Against the spirit of the assignment and the rule that excludes the snapshots. |

## 5. Verification

- The practice set after every change, read miss by miss, not just the score.
- A private set of 35 paraphrase, as-of, change and fee questions written from the data (kept out of the repo
  because it quotes the data).
- The harness's own synthetic self-test site, which also exercises conflicts gold and the carry-forward of a page
  that vanished from a later crawl.
- Unit tests on synthetic fixtures; lint; a fresh-clone run with an isolated interpreter and the standard library
  only; two independent runs compared answer by answer.
