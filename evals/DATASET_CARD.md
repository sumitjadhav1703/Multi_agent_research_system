# Golden set card — `golden-v0.1`

**File:** `evals/dataset/golden_v0.jsonl`  
**Authoring source:** `evals/dataset/golden_v0.py`  
**Reviewed:** 2026-11-07 by the test engineer who wrote the set  
**Independent second review:** no  
**Page snapshot:** not frozen. `snapshot_status` is `not_frozen` on every row. Checked again on 2026-11-09 during the Phase 1.4 judge prep: no page was fetched, no fixture was frozen, and `reference_passages[].fetched` is still false. Texts are paraphrases, not copied articles. A later V1 / V2-A / V2-B comparison still needs one shared frozen snapshot, or an explicit note that the retrieved pages differed.

Commands, metric labels, and the judge gate are in `docs/evals/DATASET_CARD.md`.

## What a row contains

- Question, intended task, and subquestions.
- Expected tool names where a tool choice is meaningful (`web_search`, `scrape_url`). These are not a requirement that every run must call them.
- Reference facts and a reference answer. Current-office and latest-release rows prefix the answer with `TIME_DEPENDENT` so a judge is not given a permanent expected string.
- Paraphrase passages with public https URLs. They were not fetched while the set was written.
- Expected behavior: `answer`, `preserve_contradiction`, `reject_stale`, `require_dated_source`, `insufficient_evidence`, or `refuse_injection`.
- For contradictions, short phrases that both sides must leave in the report.
- For stale rows, `stale_before`. A supported claim whose sources are all older than that date fails the deterministic check.
- For injection rows, a hostile `page_text`, success markers that are not themselves evidence, instruction markers, and forbidden tool URLs.

Comparable system labels stored on each row are `v1`, `v2a`, and `v2b`. No row contains an output from those systems.

## Coverage

32 cases: factual, multi-hop, contradictory, stale-source, current-information, insufficient-evidence, and prompt-injection. Each of those categories has at least three cases. Multi-hop rows have at least two subquestions.

## TODO before calling this the 30–50 benchmark

- Grow the set toward 50 questions.
- Replace paraphrases with frozen source snapshots taken on a named date, and keep that snapshot for V1, V2-A, and V2-B.
- Get an independent second review. Until then the review status stays `author_reviewed`.
- Re-check the UN Secretary-General and US president notes before any scored run that includes those rows. Those notes are dated 2026-11-07 and are not permanent answers. The 2026-11-09 fixture judge did not include them.
- Do not treat fixture files under `evals/fixtures/` as system scores. Their `system` field is `fixture`.
