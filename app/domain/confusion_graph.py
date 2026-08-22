"""Hybrid relation scoring and graph construction primitives."""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.db.models import RelationType


@dataclass(frozen=True, slots=True)
class RelationWeights:
    semantic: float = 0.30
    spelling: float = 0.25
    coerror: float = 0.30
    temporal: float = 0.15

    def __post_init__(self) -> None:
        weights = (self.semantic, self.spelling, self.coerror, self.temporal)
        if any(not math.isfinite(value) or value < 0.0 for value in weights):
            raise ValueError(
                "Confusion relation weights must be finite and non-negative"
            )
        if not math.isclose(sum(weights), 1.0, abs_tol=1e-6):
            raise ValueError("Confusion relation weights must sum to 1.0")


@dataclass(frozen=True, slots=True)
class RelationScores:
    semantic: float
    spelling: float
    coerror: float
    temporal: float
    total: float
    relation_type: RelationType


@dataclass(frozen=True, slots=True)
class GraphEdge:
    word_a_id: int
    word_b_id: int
    total_score: float


def _bounded(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def infer_relation_type(
    semantic: float,
    spelling: float,
    coerror: float,
    temporal: float,
    weights: RelationWeights | None = None,
) -> RelationType:
    selected_weights = weights or RelationWeights()
    values = {
        RelationType.SEMANTIC: selected_weights.semantic * semantic,
        RelationType.SPELLING: selected_weights.spelling * spelling,
        RelationType.CO_ERROR: selected_weights.coerror * coerror,
        RelationType.TEMPORAL: selected_weights.temporal * temporal,
    }
    total = sum(values.values())
    if total <= 0.0:
        return RelationType.MIXED
    values = {relation: value / total for relation, value in values.items()}
    ranked = sorted(values.items(), key=lambda item: item[1], reverse=True)
    if ranked[0][1] < 0.35:
        return RelationType.MIXED
    if ranked[0][1] - ranked[1][1] < 0.05:
        return RelationType.MIXED
    return ranked[0][0]


def score_relation(
    *,
    semantic: float,
    spelling: float,
    coerror: float,
    temporal: float,
    weights: RelationWeights | None = None,
) -> RelationScores:
    selected_weights = weights or RelationWeights()
    semantic = _bounded(semantic)
    spelling = _bounded(spelling)
    coerror = _bounded(coerror)
    temporal = _bounded(temporal)
    total = (
        selected_weights.semantic * semantic
        + selected_weights.spelling * spelling
        + selected_weights.coerror * coerror
        + selected_weights.temporal * temporal
    )
    return RelationScores(
        semantic=semantic,
        spelling=spelling,
        coerror=coerror,
        temporal=temporal,
        total=round(_bounded(total), 12),
        relation_type=infer_relation_type(
            semantic,
            spelling,
            coerror,
            temporal,
            selected_weights,
        ),
    )


def connected_components(
    edges: list[GraphEdge],
    threshold: float = 0.65,
) -> list[list[int]]:
    """Find deterministic connected components among qualifying graph edges."""
    adjacency: dict[int, set[int]] = {}
    for edge in edges:
        if edge.total_score < threshold:
            continue
        adjacency.setdefault(edge.word_a_id, set()).add(edge.word_b_id)
        adjacency.setdefault(edge.word_b_id, set()).add(edge.word_a_id)

    components: list[list[int]] = []
    visited: set[int] = set()
    for start in sorted(adjacency):
        if start in visited:
            continue
        stack = [start]
        component: list[int] = []
        visited.add(start)
        while stack:
            current = stack.pop()
            component.append(current)
            for neighbour in sorted(adjacency[current], reverse=True):
                if neighbour not in visited:
                    visited.add(neighbour)
                    stack.append(neighbour)
        components.append(sorted(component))
    return sorted(components, key=lambda component: (-len(component), component))
