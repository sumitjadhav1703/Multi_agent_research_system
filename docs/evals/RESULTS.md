# Evaluation results

**Run date of this file:** 2026-11-07  
**Dataset:** `golden-v0.1` (32 questions). See `evals/DATASET_CARD.md`.  
**Systems compared:** none. V1, V2-A, and V2-B have not been run on this set.  
**Frozen source snapshot:** no.

## LLM-judge metrics

Not measured. No mean, median, or per-category judge score exists. A null score is not a zero.

Pinned for a future controlled run: DeepEval `4.3.3`, LiteLLM model `gemini/gemini-flash-latest`, temperature 0. That model was not called.

On 2026-11-07 a dry run with DeepEval 4.3.3 loaded from `/tmp/deepeval_inspect` (not installed into `/tmp/rm_v2_venv`) constructed `LiteLLMModel` and the nine metric classes. Every metric score in that report was null. `measured` was false. A sentinel `.env` in the working directory was not copied into the report. This was `test_dry_run_constructs_litellm_model_without_reading_env_file`. It is not a quality result.

## Deterministic checks

These are pass/fail codes on hand-built fixture artifacts (`system: fixture`), not quality scores for a research system.

On 2026-11-07 the fixture self-check reported `dataset=32 runs=20 fixture_mismatches=0 unlabeled_issues=0`. `python -m unittest discover -s evals/tests -v` reported 14 tests, OK. Those counts are checks of the harness and the hand-built fixtures. They are not a baseline-versus-V2 table.

## What is still required for a comparison report

- Saved outputs for V1, V2-A, and V2-B on the same questions.
- A frozen source snapshot, or an explicit note that search results differed.
- A judge run with the pinned model, DeepEval pin, dataset version, case count, and date.
- Deterministic citation results reported separately from judge scores.
