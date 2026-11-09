"""Offline ResearchMind evaluation package.

DeepEval is not imported here. Public API requests must not import this
package to score a user run.
"""

DATASET_VERSION = "golden-v0.1"
# Meta Model API (https://dev.meta.ai) via LiteLLM `meta/` route.
# Contributor tier is the cheap eval path; not on the public free allowlist.
EVALUATOR_MODEL = "meta/muse-spark-1.3-contributor"
DEEPEVAL_PIN = "4.3.3"
