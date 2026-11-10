# Evaluation strategy

**Primary framework:** DeepEval (selected in SoT) — **do not replace with RAGAS**  
**Harness:** `evals/` · pin `deepeval==4.3.3` in `evals/requirements.txt` only  
**Results file:** [`../evals/RESULTS.md`](../evals/RESULTS.md) — judge scores exist for the 20 fixtures only; V1/V2 scores **NOT MEASURED**  
**Status:** PARTIALLY IMPLEMENTED · VERIFIED (deterministic fixtures + fixture-only judge run)

---

## Separation of concerns

| Mode | When | Runs on public request path? |
|---|---|---|
| Offline regression | CI (`evals` job: unit tests + deterministic self-check) / local | **No** |
| Development evaluation | Engineer laptop with keys | **No** |
| Optional production sampling | Not enabled | **No** |

Full LLM-as-judge must never auto-run for every demo request.

Gate for judge: `RM_EVAL_JUDGE=1` and `--confirm-offline`. Sets `DEEPEVAL_DISABLE_DOTENV=1`, `DEEPEVAL_TELEMETRY_OPT_OUT=1`, `LITELLM_MODE=PRODUCTION` before import.

---

## Dataset

Proposed layout (brief) vs **actual** repo layout:

```text
evals/
  dataset/golden_v0.jsonl      # actual — golden-v0.1, 32 cases
  fixtures/runs.json           # hand-built fixture artifacts
  checks.py                    # deterministic evaluators
  judge.py                     # DeepEval harness
  cli.py / __main__.py
  tests/
docs/evals/
  DATASET_CARD.md              # commands + metric labels
  RESULTS.md
  failure-analysis.md
  published-summary.json       # single source for console, API, MCP
  META_MUSE_JUDGE_SUMMARY.json
evals/DATASET_CARD.md          # dataset contents + review limits
```

`golden-v0.1` includes multi-hop, contradictory, stale, current, insufficient-evidence, and prompt-injection cases. Passages are paraphrases. `snapshot_status: not_frozen`. `independent_second_review: false`. Expansion toward 50 + frozen snapshots remains open.

---

## Retrieval metrics (deterministic when labels exist)

| Metric | Use | Status |
|---|---|---|
| Precision@K | Ranked source relevance | Methodology ready; **NOT MEASURED** on live systems |
| Recall@K | Coverage of expected sources | Same |
| MRR | First relevant rank | Same |
| NDCG | Graded relevance | Same |

Prefer plain Python metrics over LLM judges when human relevance labels exist.

---

## Research quality metrics (DeepEval / LLM-judge)

Investigated for controlled runs (DeepEval 4.3.3 classes constructed in dry-run):

- Faithfulness  
- Answer Relevancy  
- Contextual Precision / Recall  
- Tool Correctness / Argument Correctness  

**Actual scores:** recorded 2026-11-09 on the 20 hand-built fixtures only (`meta/muse-spark-1.3-contributor`: faithfulness 0.925, answer relevancy 0.700, contextual precision 0.833, contextual recall 0.667; 80 numeric scores, 0 errors). None for V1 or V2 research output. Null ≠ 0. Default threshold 0.5 is library default, not a calibrated bar.

Contextual Precision/Recall skipped for `TIME_DEPENDENT` reference answers in harness design.

---

## Agent metrics

Task Completion, Plan Adherence, Step Efficiency require traces. Public graph is **not** wrapped in DeepEval tracing → these stay **skipped** unless a saved traced run exists.

---

## Engineering metrics (ops)

Tracked structurally via usage ledger / events; host aggregates **NOT MEASURED**:

- End-to-end latency, p50/p95  
- Token consumption, estimated cost (often null)  
- Source retrieval success rate  
- Citation precision (deterministic checks on fixtures only so far)  
- Workflow completion / failure / recovery rates  

---

## Building the golden set (process)

1. Author questions with expected answer notes and reference evidence ids.  
2. Label retrieval relevance where possible.  
3. Freeze source snapshots before comparing systems (currently **not frozen**).  
4. Version dataset id (`golden-v0.1`) and record date.  
5. Run deterministic checks first.  
6. Run judge only with the pinned model (`meta/muse-spark-1.3-contributor`, `EVALUATOR_MODEL`); contributor tier may let Meta train on prompts, so use synthetic or public data.  
7. Control judge variance: temperature 0, pinned DeepEval, fixed prompt versions, multiple seeds if scoring.  
8. Cap eval cost: tiny batch, mock where possible, never on Render request path.

---

## Baseline vs improved comparison

Required for a portfolio quality claim (still open per RESULTS.md):

- Saved outputs for V1, V2-A, V2-B on the same questions  
- Frozen sources or explicit note that search differed  
- Judge run metadata (model, pin, date, case count)  
- Deterministic citation results reported separately from judge means  

Until then, resume bullets must not claim “X% quality improvement.”

---

## Fixture self-check evidence

```text
dataset=32 runs=20 fixture_mismatches=0 unlabeled_issues=0
evals/tests: 15 OK
```

These validate the harness and hand-built fixtures — **not** V1 vs V2 research quality.
