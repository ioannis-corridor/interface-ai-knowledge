# Question sets (not committed)

The question sets quote the credit union's real rates and URLs, and that data is shared for this
event only. This repository is public, so they are git-ignored. Copy them in before running the
scorer:

- `public_eval.jsonl` — the 40 practice questions. Comes with the official kit; copy it from
  there into this directory.
- `extra_eval.jsonl` — our own 35-question regression set (paraphrases, as-of dates, changes,
  fees), written from reading the snapshots. Ships alongside the kit data, not in the repo.

`scripts/check.sh` skips both runs when the files are absent. The synthetic harness self-test
(`harness/selftest/`) needs neither and always runs.
