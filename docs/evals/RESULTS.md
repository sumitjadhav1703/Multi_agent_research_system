# Evaluation results

**Run date of this file:** 2026-11-09  
**Dataset:** `golden-v0.1` (32 questions). See `evals/DATASET_CARD.md`.  
**Systems compared:** none. V1, V2-A, and V2-B have not been run on this set.  
**Frozen source snapshot:** no. `snapshot_status` remains `not_frozen`.

## LLM-judge metrics

The offline judge is now configured to Meta Llama 8B: `EVALUATOR_MODEL = meta_llama/Llama-3.3-8B-Instruct` with `LLAMA_API_KEY` in the process environment. That model is not on the public free allowlist and is not a frontend provider. A Meta 8B scoring run has not been recorded yet; the numeric cell below remains the earlier Gemini fixture probe and is not a Meta result.

A controlled judge did run. It scored two hand-built fixture artifacts, not a research system. A null score below is a null. It is not a zero, and it is not included in any average.

| Field | Value |
|---|---|
| Date | 2026-11-09 |
| Dataset | `golden-v0.1` |
| Cases judged | 2 of 32 (`clean_factual` / g001, `contradiction_kept` / g014) |
| `system` | `fixture` (`is_benchmark` false) |
| DeepEval | 4.3.3, matching the pin |
| LiteLLM | 1.108.2 |
| Evaluator | `gemini/gemini-flash-latest`, temperature 0 |
| Threshold | 0.5, DeepEval 4.3.3's library default, not a calibrated ResearchMind bar |
| Python | 3.13.14, `/tmp/rm_eval_judge` |
| Wall time | about 534 seconds |
| Process exit | 1, because at least one metric status was `error` |
| Numeric scores | 1 |
| Eligible metrics left null | 7 |
| Metrics skipped by the harness | 10 |

Keys were loaded from the local `.env` with python-dotenv into the process environment and were not printed. The command set `RM_EVAL_JUDGE=1`, `DEEPEVAL_DISABLE_DOTENV=1`, `DEEPEVAL_TELEMETRY_OPT_OUT=1`, and `LITELLM_MODE=PRODUCTION`. It called `metric.measure()` only. It did not call `deepeval.evaluate()`.

LiteLLM logged a deprecation warning that temperature still works for Gemini 3+ (`gemini-flash-latest`). That warning is not a score.

### Scores that were returned

| Run | Case | Category | Metric | Score |
|---|---|---|---|---|
| `clean_factual` | g001 | factual | Answer Relevancy | 1.0 |

The judge's reason for that single score was that the fixture report answered the Australia-capital question with relevant information. One observed value has no mean or median across cases. g014 has no Answer Relevancy score.

No other metric returned a number. There is no faithfulness mean, no contextual-precision mean, no contextual-recall mean, and no category table beyond the one cell above.

### Eligible metrics left null

| Run | Metric | Status | Why the score is null |
|---|---|---|---|
| `clean_factual` | Faithfulness | error | `TimeoutError`: call timed out after 88.5s per attempt |
| `clean_factual` | Contextual Precision | error | same 88.5s timeout |
| `clean_factual` | Contextual Recall | error | same 88.5s timeout |
| `contradiction_kept` | Faithfulness | error | same 88.5s timeout |
| `contradiction_kept` | Answer Relevancy | error | LiteLLM `ServiceUnavailableError`, Gemini HTTP 503, high demand |
| `contradiction_kept` | Contextual Precision | error | same HTTP 503 |
| `contradiction_kept` | Contextual Recall | error | same HTTP 503 |

The raw JSON is local and gitignored: `evals/results/judge-subset-2026-11-09.json`.

### Skipped on purpose

Both fixtures have empty `tool_calls` and `trace: null`. Tool Correctness, Argument Correctness, Task Completion, Plan Adherence, and Step Efficiency stayed skipped. Ten skip rows, five on each case. Their scores are null.

### What this run is not

It is not a V1 versus V2 comparison. It is not a 32-question benchmark. The passages are still paraphrases. The 2026-11-07 dry run, which constructed `LiteLLMModel` and the nine metric classes and stored only nulls, is still not a quality result. A repeat dry run on 2026-11-09 with `/tmp/rm_eval_judge` covered all 20 fixture runs: `measured` false, DeepEval 4.3.3, 180 metric rows, 0 non-null scores.

## Deterministic checks

These are pass/fail codes on hand-built fixture artifacts (`system: fixture`), not quality scores for a research system.

On 2026-11-09 the fixture self-check reported `dataset=32 runs=20 fixture_mismatches=0 unlabeled_issues=0`. `python -m unittest discover -s evals/tests -v` reported 14 tests, OK, in 3.228s, with 0 skipped and 0 failed. Those counts check the harness and the fixtures. They are not a baseline-versus-V2 table.

## Commands

```text
PYTHONPATH=. /tmp/rm_v2_venv/bin/python -m unittest discover -s evals/tests -v
PYTHONPATH=. /tmp/rm_v2_venv/bin/python -m evals.cli deterministic
```

The judge used `/tmp/rm_eval_judge/bin/python -m evals.cli judge --confirm-offline` on a two-run subset. DeepEval stays out of `/tmp/rm_v2_venv` so the missing-install test still exits 3.

## What is still required for a comparison report

- Saved outputs for V1, V2-A, and V2-B on the same questions.
- A frozen source snapshot, or an explicit note that search results differed.
- A judge run that returns numeric scores for the metrics being compared, with the same model, DeepEval pin, dataset version, case count, and date.
- The 2026-11-09 run does not supply those scores. Timeouts and HTTP 503 left seven eligible scores null.
- Deterministic citation results reported separately from judge scores.
