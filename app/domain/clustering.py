"""Graph-based confusion clustering helpers."""

from __future__ import annotations

from app.domain.confusion_graph import GraphEdge, connected_components


def cluster_word_ids(edges: list[GraphEdge], threshold: float) -> list[list[int]]:
    return connected_components(edges, threshold)


def select_core_word_ids(
    component: list[int],
    edges: list[GraphEdge],
    limit: int = 8,
) -> list[int]:
    """Keep highest weighted-degree words when a component is too large."""
    if len(component) <= limit:
        return component
    component_set = set(component)
    weighted_degree = {word_id: 0.0 for word_id in component}
    for edge in edges:
        if edge.word_a_id in component_set and edge.word_b_id in component_set:
            weighted_degree[edge.word_a_id] += edge.total_score
            weighted_degree[edge.word_b_id] += edge.total_score
    return [
        word_id
        for word_id, _score in sorted(
            weighted_degree.items(), key=lambda item: (-item[1], item[0])
        )[:limit]
    ]
