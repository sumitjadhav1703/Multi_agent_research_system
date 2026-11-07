"""Hard ceilings for the public research graph.

Lower values are allowed. Higher values are clamped back to the Milestone 2
bounds from the source of truth: 3 subquestions, 2 workers, 6 sources, 4
searches, 1 evidence retry and 1 report revision. PDF parsing stays off.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GraphLimits:
    max_subquestions: int = 3
    max_parallel_workers: int = 2
    max_sources: int = 6
    max_search_calls: int = 4
    max_evidence_retries: int = 1
    max_revisions: int = 1
    max_fetches_per_worker: int = 2
    max_passages_per_source: int = 2
    max_passage_chars: int = 500
    max_excerpt_chars: int = 2000
    max_model_calls: int = 12
    max_topic_chars: int = 500
    max_search_results: int = 3
    pdf_enabled: bool = False

    def clamped(self) -> GraphLimits:
        return GraphLimits(
            max_subquestions=_bound(self.max_subquestions, 1, 3),
            max_parallel_workers=_bound(self.max_parallel_workers, 1, 2),
            max_sources=_bound(self.max_sources, 1, 6),
            max_search_calls=_bound(self.max_search_calls, 1, 4),
            max_evidence_retries=_bound(self.max_evidence_retries, 0, 1),
            max_revisions=_bound(self.max_revisions, 0, 1),
            max_fetches_per_worker=_bound(self.max_fetches_per_worker, 1, 2),
            max_passages_per_source=_bound(self.max_passages_per_source, 1, 2),
            max_passage_chars=_bound(self.max_passage_chars, 80, 500),
            max_excerpt_chars=_bound(self.max_excerpt_chars, 80, 2000),
            max_model_calls=_bound(self.max_model_calls, 0, 12),
            max_topic_chars=500,
            max_search_results=_bound(self.max_search_results, 1, 3),
            pdf_enabled=False,
        )


def _bound(value: int, low: int, high: int) -> int:
    return max(low, min(int(value), high))
