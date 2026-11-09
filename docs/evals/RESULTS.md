# Evaluation results

**Run date of this file:** 2026-11-09  
**Dataset:** `golden-v0.1` (32 questions). See `evals/DATASET_CARD.md`.  
**Systems compared:** none. V1, V2-A, and V2-B have not been run on this set.  
**Frozen source snapshot:** no. `snapshot_status` remains `not_frozen`.

## LLM-judge metrics (Meta Model API — current)

Offline DeepEval scored the **20 hand-built fixture runs** (`system: fixture`) with Meta Model API Muse Spark **contributor** via LiteLLM. This is **not** a V1 versus V2 research-system table. Means exclude skipped/null rows. A null is not a zero. Contributor tier may allow Meta training on prompts; fixtures are synthetic.

| Field | Value |
|---|---|
| Date | 2026-11-09 |
| Dataset | `golden-v0.1` |
| Fixture runs judged | 20 |
| `system` | `fixture` |
| DeepEval | 4.3.3 |
| Evaluator | `meta/muse-spark-1.3-contributor`, temperature 0 |
| Auth | `META_API_KEY` (aliases `MODEL_API_KEY` / `LLAMA_API_KEY`), process env only |
| Threshold | 0.5 (DeepEval library default, not a calibrated ResearchMind bar) |
| Wall time | about 1912 seconds |
| Process exit | 0 |
| Numeric scores | 80 |
| Errors | 0 |
| Published summary | `docs/evals/published-summary.json` (also API + Evaluation console) |

### Metric means (numeric rows only)

| Metric | Mean | n |
|---|---|---|
| Faithfulness | 0.925 | 20 |
| Answer relevancy | 0.700 | 20 |
| Contextual precision | 0.833 | 18 |
| Contextual recall | 0.667 | 18 |
| Tool correctness | 0.250 | 2 |
| Argument correctness | 0.000 | 2 |
| Task completion | skipped | no DeepEval trace on fixtures |
| Plan adherence | skipped | no DeepEval trace on fixtures |
| Step efficiency | skipped | no DeepEval trace on fixtures |

Raw JSON is local/gitignored: `evals/results/meta-muse-full.json`. Compact means: `docs/evals/META_MUSE_JUDGE_SUMMARY.json`.

### Note on retired `meta_llama/` route

Meta retired the Llama API public preview (`api.llama.com`). Keys from https://dev.meta.ai/ are **Meta Model API** keys (`LLM_…`) and must use LiteLLM `meta/muse-spark-…` with `META_API_KEY`, not `meta_llama/Llama-3.3-8B-Instruct`.

## Historical Gemini fixture probe (archive)

Earlier the same day, a bounded Gemini Flash probe on 2 fixtures recorded one Answer Relevancy of 1.0 and left other eligible metrics null (timeouts / HTTP 503). That probe is superseded by the Meta Muse run above for the published Evaluation page.

## Deterministic checks

Pass/fail codes on hand-built fixture artifacts (`system: fixture`), not quality scores for a research system.

On 2026-11-09 the fixture self-check reported `dataset=32 runs=20 fixture_mismatches=0 unlabeled_issues=0`. Raw: `evals/results/deterministic-2026-11-09.json`. Published with the judge summary above.

## Commands

```text
PYTHONPATH=. python -m unittest discover -s evals/tests -v
PYTHONPATH=. python -m evals.cli deterministic
RM_EVAL_JUDGE=1 PYTHONPATH=. python -m evals.cli judge --confirm-offline --output evals/results/meta-muse-full.json
```

## What is still required for a comparison report

- Saved outputs for V1, V2-A, and V2-B on the same questions.
- A frozen source snapshot, or an explicit note that search results differed.
- The Meta Muse fixture run above is a harness probe, not that comparison.
