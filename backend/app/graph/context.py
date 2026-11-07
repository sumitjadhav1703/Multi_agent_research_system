"""Runtime dependencies that are not part of checkpointed graph state."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.app.graph.limits import GraphLimits


@dataclass
class GraphContext:
    model_client: Any
    retrieval: Any
    limits: GraphLimits
