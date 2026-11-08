# Evaluation commands and metric labels

Dataset contents, review limits, and the expansion TODO are in `evals/DATASET_CARD.md`. This file is how to run the checks and how to read the two kinds of result.

**Dataset:** `golden-v0.1`, 32 author-reviewed questions, no frozen page snapshot, no independent second review.  
**Judge pin:** DeepEval `4.3.3`, LiteLLM model `gemini/gemini-flash-latest` (same id as `EVAL_JUDGE_PRIMARY_MODEL` in `.env.example`). Temperature 0.  
**Threshold 0.5:** DeepEval 4.3.3's library default. It is not a calibrated ResearchMind pass bar.  
**Python:** `/tmp/rm_v2_venv/bin/python` (3.13). Run from the repository root with `PYTHONPATH=.`.

No scores in this card were produced by a model.

## Two kinds of result

| Kind | What it is | When it runs |
|---|---|---|
| Deterministic | Python checks over a saved run artifact: citation integrity, passage consistency, contradiction preservation, duplicate sources, quota and tool budget, static URL safety, and expected-behavior compliance | Local command below. Not wired into GitHub Actions. |
| LLM judge | DeepEval Faithfulness, Answer Relevancy, Contextual Precision, Contextual Recall, Tool Correctness, Argument Correctness, Task Completion, Plan Adherence, and Step Efficiency | Only with `RM_EVAL_JUDGE=1` and `--confirm-offline`. Never on a public request. |

Null judge scores are not zeros. Fixture runs are not V1 or V2 benchmark rows.

Trace-only metrics (Task Completion, Plan Adherence, Step Efficiency) stay skipped unless the saved run has a `trace` object. The public research graph is not wrapped in DeepEval `@observe`. Contextual Precision and Contextual Recall are skipped when the reference answer starts with `TIME_DEPENDENT`, because that answer is a dated review note.

Static URL safety does not resolve DNS and does not replace `tools.validate_public_url`. SSRF is not closed.

## Deterministic command

```text
PYTHONPATH=. /tmp/rm_v2_venv/bin/python -m evals.cli deterministic \
  --dataset evals/dataset/golden_v0.jsonl \
  --runs evals/fixtures/runs.json
```

```text
PYTHONPATH=. /tmp/rm_v2_venv/bin/python -m unittest discover -s evals/tests -v
```

The fixture file's `expect_issue_codes` values are the harness self-check. A real saved run should omit that field. Any issue then makes the command exit 1.

Refresh the JSONL after editing the authoring module:

```text
PYTHONPATH=. /tmp/rm_v2_venv/bin/python -m evals.dataset.golden_v0
PYTHONPATH=. /tmp/rm_v2_venv/bin/python evals/fixtures/make_runs.py
```

## Judge command

Export `GEMINI_API_KEY` or `GOOGLE_API_KEY` in the process environment. The command sets `DEEPEVAL_DISABLE_DOTENV=1`, `DEEPEVAL_TELEMETRY_OPT_OUT=1`, and `LITELLM_MODE=PRODUCTION` before import so DeepEval and LiteLLM do not read a `.env` file. Do not print those keys.

Keep DeepEval out of `/tmp/rm_v2_venv`. The unit test that expects exit code 3 runs with that interpreter and a clean `PYTHONPATH`. Install the judge extra in a separate environment. `deepeval==4.3.3` does not depend on LiteLLM, and `LiteLLMModel` imports it only when a completion runs, so `evals/requirements.txt` also pins `litellm==1.108.2` (the backend pin).

```text
uv venv /tmp/rm_eval_judge --python python3.13
uv pip install --python /tmp/rm_eval_judge/bin/python -r evals/requirements.txt
```

Constructor check, no model call and no scores:

```text
RM_EVAL_JUDGE=1 PYTHONPATH=. /tmp/rm_eval_judge/bin/python -m evals.cli judge \
  --confirm-offline \
  --dry-run \
  --runs evals/fixtures/runs.json \
  --output evals/results/judge-dry-run.json
```

A real judge call, still offline from the public API, and only against saved run artifacts (this does not start a research job):

```text
RM_EVAL_JUDGE=1 PYTHONPATH=. /tmp/rm_eval_judge/bin/python -m evals.cli judge \
  --confirm-offline \
  --runs path/to/saved-runs.json \
  --output evals/results/judge.json
```

Load `GEMINI_API_KEY` or `GOOGLE_API_KEY` into that process with dotenv. Do not print the values. `LiteLLMModel` forwards `GOOGLE_API_KEY` when that variable is set. `evals/results/` is gitignored. Without the flag or `--confirm-offline`, the command exits 2. Without DeepEval installed, it exits 3. It does not call `deepeval.evaluate()`, which can sync to Confident AI. It calls `metric.measure()` on eligible metrics only.

A dry run on 2026-11-07 constructed the metric classes and recorded only null scores. On 2026-11-09 a two-fixture judge called `gemini/gemini-flash-latest` and recorded one numeric score. The other eligible scores stayed null. See `docs/evals/RESULTS.md`.
