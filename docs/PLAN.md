# Plan: "knows what's true now" knowledge system (interface.ai build assignment)

## Revision 2 (after self-review)

Checked the plan against the data and the scorer. Architecture unchanged (deterministic fact layer + retrieval + optional LLM). Changes:

- Practice weight splits prose/entity 43%, rate tables 41%, refusals 9%, URL/link 7%. Prose extraction and URL answers move into Phase 1-2, not after tables.
- New intents: URL/link, what-changed/before-after, repeat-noise words, as_of "did not exist yet", cross-branch aggregation.
- The LLM's one job is question parsing (structured output, temperature 0, hard timeout, rules fallback). Composition is always deterministic.
- Scorer hygiene rules become a validator: one value per fact, no later values in as_of answers, refusals add no numbers, plain text (no markdown: `***` is a trap value), every number grounded in non-stale evidence, sentence-level extraction (traps like `member number`, `ZIP code`, `CO-OP Shared Branch` sit on the same pages as the right answers).
- Authority is comparative: rank sources only when they disagree on the same fact key. Verified on branch count: posts dated Apr-May 2026 say 22, Feb-Mar 2026 say 23, older say 24/20. Newest article date wins; undated posts fall back to `fetched_at`.
- Conflicts calibrated for F1: one entry per fact key, within-latest stale copies first, cross-snapshot changes second, capped. New verified example: `/newcard-balancetransfer-lp` says checking "up to 3.00% APY" while the rate sheet says 2.50%.
- Simplified: one chunk index with snapshot membership (body text ~90% identical across crawls), no disk cache.

## 1. What the scorer actually rewards (decoded from `harness/scoring.py`)

| Rule in the scorer | Design consequence |
| --- | --- |
| `must_include` / `must_not_include` are matched **by numeric value** (`5.39%` == `5.390 %`). One trap value anywhere in the text zeroes the item. | Say **one value, the right one**. Never list other tiers, old values, or "both numbers" unless the question asks for the whole table. |
| `should_refuse` items pass only if the answer refuses (`confident=False` or a refusal phrase) **and contains no number not already in the question**. | Refusal text must contain **no digits at all** - not even the 800 phone number. |
| Source credit is a **path-level URL match** (fragment and query dropped). 15% of an item when the item lists sources. | Always cite the authoritative page URL (e.g. `/personal/loans/home-loans`); `#rates` fragments are irrelevant. |
| Consistency = same **set of numbers** across paraphrases and across repeat calls, multiplied by accuracy. | Deterministic pipeline, stable tie-breaking, answer cache keyed on normalized question + `as_of`. |
| Speed = p95 latency <= 2 s for full marks, 0 at 20 s, multiplied by accuracy. | Everything in memory; at most one small LLM call per answer; cache. |
| Conflicts = 0.7 x F1 against a gold list + 0.3 x right-winner. Each gold entry matches at most one submitted conflict. | Precision matters: emit a **curated, deduped** list (one entry per fact, not per page pair), with topic strings that carry the natural keywords and values formatted like the site (`5.34%`). |
| Hard items weigh 2.0, easy 1.0. Categories: stale_trap, tier_disambiguation, should_refuse, branch_info, conflict_resolution, temporal_as_of, list_completeness, entity_attribution, current_value. | Stale-trap and tier handling dominate the accuracy pillar. |

Two other observations from the practice set:

- Many `must_not_include` values **do not exist anywhere in the snapshots** (`271176899`, `9.9%`, `6.7%`, `up to 0.35`, `info.dupaco.com/certificate_account_rates`, `coffee table`, `I'm not asking again`). These are hallucination traps from a real chatbot's failures. A grounded system wins them for free.
- `expected_answer` strings reveal the intended behaviour for ambiguous questions: lead with the $100k mortgage tier, read back all CD terms instead of asking which term, give typical lobby hours then ask which branch, do not demand a ZIP code first.

## 2. What the data looks like (findings from reading the snapshots)

- 637 -> 634 -> 635 -> 683 -> 705 pages, ~5 MB of markdown per snapshot. Small enough for pure in-memory Python.
- Byte-level diffs are useless: 615 of 633 common pages "changed" between crawl 1 and 2, almost all nav/footer noise (`Third Party Plugins`, `Messenger`). Change detection must run on **extracted facts / normalized body text**, not raw bytes.
- `/rates` and `/business-rates` are master rate sheets. In the latest snapshot there are 104 rate-like tables on 28 pages, 182 unique tables by content (heavy duplication across pages). **Every rate table ends with `Rates are effective as of MM/DD/YYYY`** - an explicit, extractable recency signal that is more trustworthy than crawl date.
- The product label for a table is a **plain text line above it** (`Share Savings`, `Special Certificates`), not a markdown heading. Older pages drop the `Account Type` column entirely, so the label must be inferred from the nearest label line above.
- Stale copies live on predictable page types: calculators (`/calculators/vehicle-affordability`), promo landing pages (`/switch-and-earn`, `*-lp`), `/homebuying-guidance` (a 6.000%/6.037% mortgage table from months ago), `/personal/checking-accounts` (embeds an old auto-loan table), and old newsroom boilerplate (`24 branch office locations`, `fourth time Forbes recognized Dupaco`).
- Tier labels drift: auto tiers were `2023-26 Model Year` until August and `2024-27 Model Year` in September. "2025 model year" has to be resolved by **range containment**, not label equality.
- Real intra-snapshot contradictions exist: in September, `/personal/retirement` lists `Roth: 10 Month Fixed Jumbo Special 4.00%` and `Traditional: 10 Month Fixed Jumbo Special 3.90%` in the same table.
- Rate vs APY: certificate tables have both columns. Members say "rate" and the expected answers use the APY (`3.90%`). Headline the APY, optionally add the dividend rate, never a neighbouring tier.
- Branch hours exist only in newsroom posts (lab/branch opening releases); the `/contact` locator widget shows addresses and `Closed`. Authority rules must be **fact-type aware**: rates pages beat everything for rates, but for hours the newest dated press release is the best source.
- `fetched_at` inside a snapshot is a second recency signal: 24 pages in the September snapshot were last fetched in June or August.
- The 17-month certificate special is absent in both May crawls, then 3.85% (June), 3.95% (August), 4.10% (September). `as_of` answers must handle "not offered then", and products like this are prime "what changed" targets.
- Prose facts carry dates in the body (`June 20, 2025` near the top of newsroom posts). The Hy-Vee closure answer comes from a 2025 release that nothing newer contradicts; the branch count comes from the newest release that mentions it. Old is not stale by itself.

## 3. Architecture

Hybrid: a **deterministic core** (parsing, indexing, ranking, composing, conflicts) that scores on its own, plus an **optional LLM parser** for question understanding only. If no API key is present, a rules parser produces the same structured query. Composition is never delegated to the LLM: the scorer zeroes exactly what LLMs do by default (list both values, hedge, add a minimum-deposit figure), and the fact layer is needed anyway to know which chunk is stale.

```
ingest(snapshot)                       answer(question, as_of)                 conflicts()
  |                                      |                                        |
  normalize markdown                      canonicalize question                   group facts by key
  classify page (authority tier)          (synonyms, numbers, stopwords)          across pages + snapshots
  extract facts from tables               detect intent + qualifiers              keep keys with >1 value
    + regex entity facts                  (term, tier, model year, product,       resolve by policy
  chunk text into sections                 balance, metric, wants-all-tiers)      dedupe, rank, cap
  build BM25 index per snapshot           pick snapshot(s) for as_of
  update fact timeline                    fact lookup + BM25 chunks
  (first_seen, last_seen, by snapshot)    rank: relevance x authority x recency
                                           x stale penalty
                                          compose: template (structured) or
                                           LLM (free text) + numeric validator
                                          refuse if evidence weak; cache
```

### 3.1 Ingest

1. **Normalize**: strip nav/footer/boilerplate (repeated blocks across many pages), collapse whitespace, decode entities.
2. **Classify page** by URL pattern and content: `rates` (`/rates`, `/business-rates`) > `product` (`/personal/*`, `/business/*` product pages) > `info` (contact, about, membership) > `newsroom` (dated; newer beats older) > `learn/blog` > `calculator` / `*-lp` / promo (`/switch-and-earn`, `/homebuying-guidance`) > `hubfs` files. This is the written-down authority policy the assignment asks for.
3. **Extract structured facts from markdown tables**: parse header + rows; attach the nearest label line above the table; pull `effective as of` date; normalize cells into a fact key: `(product_family, product, qualifiers{term_months, model_year_range, balance_range, loan_amount_range, ira_type, purpose}, metric{APY, dividend_rate, APR, rate, min_to_earn, ...})` -> value. One row can produce several facts (APY and dividend rate).
4. **Extract entity facts with regexes** from prose: branch/employee/member counts and assets from the "About Dupaco" boilerplate, routing number, phone numbers, addresses + hours blocks, "Nth time Forbes", closure dates ("scheduled to close March 31, 2026"), article dates on newsroom/blog posts.
5. **Chunk text** by heading/section (keep tables intact as one chunk), with metadata: url, title, snapshot_id, page class, effective date, article date, fetched_at.
6. **Index**: one BM25 index over unique chunks (own ~50-line implementation or `rank_bm25`), each chunk tagged with the set of snapshot ids and URLs where it appears; filter by snapshot at query time. Plus a dictionary index for facts. Cite the most authoritative URL first.
7. **Fact timeline**: for every fact key and URL, record value per snapshot. This is the "keep history, not just the latest copy" requirement, and it powers `as_of`, change questions, and conflicts.

Ingest cost estimate: parsing 3,300 pages of markdown in Python takes seconds, far under the 30-minute limit. No disk cache needed.

### 3.2 Answer

1. **Canonicalize** the question: lowercase, expand synonyms (CD <-> certificate, mortgage <-> home loan, car/vehicle <-> auto, APY <-> rate for deposits, "five-year" -> 60 months), normalize numbers and dates, strip stopwords. Paraphrases converge to the same query, which is what the consistency pillar measures.
2. **Detect intent and qualifiers**. Intents: `fact_lookup` (rate, fee, hours, address, routing, count), `list` ("what certificates/cards do you offer", all CDs, personal + business cards), `link` ("what link/URL/where do I go to see X": the answer text itself must contain the authoritative page URL), `change` ("did X change", "what was X before", "how has X moved since May": answer from the fact timeline with old and new values, dates attached), `status` ("is the Hy-Vee branch still open": compare closure date with the as-of date), `aggregate` ("do all branches keep the same hours": gather per-branch facts and report the distinct schedules), `free_text` (eligibility, how-to, product descriptions). Qualifiers: term, model-year range, balance or loan-amount range, product name, personal vs business, metric (APY vs dividend rate vs APR). Noise words to drop: "repeat", "again", "can you tell me". Rules parser first; the optional LLM parser emits the same structured query (one call, temperature 0, 5 s timeout, fall back to rules on any failure).
3. **Select snapshot**: `as_of=None` -> latest. `as_of=date` -> newest snapshot with `taken_on <= as_of`; if the date precedes the first snapshot, use the first and let table `effective as of` dates extend validity backward. If `as_of` is missing but the question says "as of May 2026", parse the phrase. If the product or tier has no fact in the selected snapshot, say it was not offered or listed then (no numbers).
4. **Retrieve**: structured fact lookup when intent is a rate/fee/hours/address/routing lookup; BM25 over chunks for everything else; both for mixed questions.
5. **Rank**: relevance x authority prior x recency (effective date, article date, fetched_at) x stale penalty. A chunk is stale when its value for fact key K disagrees with the authority value for K in the same snapshot (the calculator page showing 5.34% while `/rates` shows 5.39%). Stale chunks never contribute numbers to an answer.
6. **Compose**:
   - Structured facts -> deterministic templates: "The 60-month APR for 2024-27 model-year vehicles is 5.39% (rates effective 08/31/2026)." Pick the single matching tier; if the question gives no tier, follow the practice-set conventions (lead tier, or full list for CDs/credit cards).
   - Free text -> **sentence-level extraction** from the top non-stale chunk: pick the one to three sentences with the highest overlap with the canonical query, never the whole chunk. Traps like `member number`, `ZIP code` and `CO-OP Shared Branch` sit in the same pages as the right answers.
   - **Answer validator** (hard rules from the scorer): every number in the text appears in non-stale evidence for the selected snapshot; as_of answers contain no values from other dates (`dup-006` lists the later 4.00% as a trap); refusals contain no numbers beyond those in the question; plain text only, no markdown (`***` is a trap value); one value per fact unless the intent is `list`, `change` or `aggregate`. On a validator failure, fall back to the template answer or refuse.
7. **Refuse** when the requested (product, metric) pair has no fact in the selected snapshot even though the product exists (7/1 ARM rate, construction-loan rate, Mullan Avenue hours). This is an existence check on the fact layer, not a similarity threshold; retrieval will always find something about ARMs. `confident=False`, text without numbers, pointing to a lender or branch.
8. **Cache** by (canonical question, as_of) for repeat consistency and speed.

### 3.3 Conflicts

- Group the fact timeline by fact key. A conflict exists when (a) two pages in the same snapshot give different values for the same key (calculator vs rate page; `-lp` page "up to 3.00% APY" vs rate sheet 2.50%; Roth vs Traditional 10-month jumbo in one table), or (b) the authority value changed between snapshots and an old value is still visible on some page in the latest snapshot. Pure rate movements with no stale copy left are reported only for headline products, to protect precision. The scorer is F1 with one match per gold entry, so the list is one entry per fact key, ranked by salience, capped (target: tens, not hundreds). The latest manifest calls that crawl the "source of the open conflicts", so within-latest contradictions come first.
- Resolution policy, in order: rates/product page beats other page classes; latest `effective as of` date; latest article date for prose facts; latest snapshot; majority of authoritative pages. `reason` is a template sentence ("rate page effective 08/31/2026 is authoritative; calculator page still shows the 2023-26 tier table").
- Include prose conflicts too: branch count (22 vs 24), Forbes recognitions (fourth vs fifth), employee counts.
- Output: one `Conflict` per fact key, values formatted like the site, topic string with product + qualifier words (`60-month auto loan APR, 2024-27 model year`), sources with snapshot ids and short quotes. Cap and rank by salience so precision stays high.

## 4. Phased roadmap (each phase is runnable and scoreable)

| Phase | Build | Expected movement |
| --- | --- | --- |
| 0 | Repo scaffold: copy kit layout, `submission/solution.py`, `requirements.txt`, `NOTES.md`, `.gitignore` excluding `snapshots/`, `snapshots_zip/`, `.env`. Verify starter baseline (0.093). | Harness runs from a fresh clone. |
| 1 | Ingest, both halves: table-to-fact parser (label, effective date, tiers) **and** prose entity facts (article dates, hours blocks, addresses, counts, closure dates, routing, "Nth time Forbes"), chunking, one BM25 index, fact timeline. Unit tests on tricky tables and hours blocks. | Enables everything else. |
| 2 | Answer core: canonicalizer, rules parser with all intents (`fact_lookup`, `list`, `link`, `change`, `status`, `aggregate`, `free_text`), snapshot selection for `as_of`, tier range matching, rate-vs-APY, sentence-level extraction, templates, existence-check refusals, answer validator, cache. | all nine categories; the bulk of accuracy. |
| 3 | `conflicts()` from the fact timeline + prose entity facts, resolution policy, dedupe, ranking, cap. Score against a hand-built gold list from the traps seen so far (5.34/5.39, 5.54/5.59, 6.037/7.13, 3.90/4.00, 3.00/2.50 checking, 22/24, fourth/fifth). | conflicts pillar. |
| 4 | Optional LLM parser behind an env var: structured query, temperature 0, timeout, rules fallback. Measure score and p95 latency on and off. Same gate for an embeddings experiment: adopt only if it beats BM25 on the private paraphrase set. | paraphrase robustness, consistency. |
| 5 | Hardening: private paraphrase + `as_of` + what-changed eval set (not hard-coded into answers), repeat-run diff, latency profile, fresh-clone test in a Python 3.11 venv, `NOTES.md` (how "current" is decided, which keys are optional), final commit. | consistency, speed, submission checklist. |

## 5. Verification plan

- Run `python harness/run_eval.py --submission submission --eval eval/public_eval.jsonl` after every phase; read `results/per_question.jsonl` for misses and trap hits, not just the score.
- Keep a private `eval/private_eval.jsonl` of paraphrases, `as_of` variants for each snapshot date, and "what changed" questions, written from reading the snapshots. Use it to catch overfitting to the 40 public questions.
- Unit tests for the parsers (tables, hours blocks, dates) and for snapshot selection.
- Consistency: run the harness twice and diff answers; the cache and deterministic tie-breaking should give identical output.
- Speed: assert p95 <= 2 s with LLM off; measure with LLM on and keep the call budget to one per question.
- Fresh clone: `python3.11 -m venv`, `pip install -r requirements.txt`, run the harness end to end.

## 6. Repo and submission hygiene

- Separate public GitHub repo, not inside any work monorepo. Layout mirrors the kit: `harness/`, `eval/`, `starter/`, `submission/` (any name except `starter/`), `snapshots/README.md` only.
- `.gitignore`: `snapshots/0*/`, `snapshots_zip/`, `.env`, `results/`, caches. Confirm with `git ls-files` before the first push; the data is shared for this event only. No precomputed knowledge base derived from the snapshots goes into the repo either.
- `requirements.txt` minimal: no torch, no local embedding models. Candidate list: `rank_bm25` (or none), the LLM SDK if used, nothing else.
- `NOTES.md`: how "current" is decided (authority policy, effective-as-of dates, stale detection), how `as_of` picks a snapshot, how conflicts are resolved, which API key is optional and what happens without it, known limitations.

## 6a. Alternatives considered and set aside

| Alternative | Why not |
| --- | --- |
| Pure LLM RAG | The scorer zeroes what LLMs do by default: both values, hedges, extra figures. Speed variance and a hard key dependency in the grader's clean environment. The fact layer is still needed to know which chunk is stale. |
| Pure rules + BM25 | The floor the hybrid falls back to. Only weakness is paraphrases, which the optional LLM parser covers. |
| LLM extraction at ingest (untimed) | Tables are already structured, deterministic parsing is more reliable, hundreds of API calls in the grader's run, non-determinism moves into the knowledge base. At most a later experiment for prose pages regexes cannot cover. |
| Embeddings-first retrieval | Plausible upgrade for the prose share; adopt only if it beats BM25 on the private paraphrase set. API embeddings add a key to ingest; local models add torch. |
| Precomputed knowledge base in the repo | Against the spirit of the assignment and the "exclude the snapshots" rule. |

## 6b. Expected score shape

Accuracy drives roughly 85% of the final number because speed and consistency are multiplied by it. A plausible strong result: accuracy 0.85, consistency 0.95, speed 1.0, conflicts 0.6 -> about 0.80 overall. Conflicts is the pillar with the most uncertainty because the gold list is hidden; precision discipline is the lever.

## 7. Decisions needed before implementation

1. **LLM layer**: do you have an API key you want to use (OpenAI, Anthropic, other)? Options: (a) deterministic only, (b) deterministic core + optional LLM behind an env var (recommended), (c) LLM required. Note the grader runs in a clean environment; (b) keeps the submission working if the key is absent.
2. **Repo**: create the public GitHub repo under your account and share the remote, or I build the code in a standalone folder and hand it over as an archive for you to push.
3. **Dependency appetite**: pure standard library versus a small set (`rank_bm25`, LLM SDK). Both fit the 2-second budget.
4. **Submission folder name** (default `submission/`).
