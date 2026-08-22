from __future__ import annotations

import pytest

from app.domain.confusion_graph import (
    GraphEdge,
    RelationWeights,
    connected_components,
    score_relation,
)


def test_adapt_adopt_adept_form_connected_component() -> None:
    edges = [
        GraphEdge(1, 2, 0.87),
        GraphEdge(2, 3, 0.76),
        GraphEdge(4, 5, 0.40),
    ]
    assert connected_components(edges, 0.65) == [[1, 2, 3]]


def test_relation_total_uses_configured_formula() -> None:
    scores = score_relation(
        semantic=0.5,
        spelling=0.8,
        coerror=1.0,
        temporal=1.0,
    )
    assert scores.total == 0.8


def test_relation_weights_reject_negative_values_even_when_sum_is_one() -> None:
    with pytest.raises(ValueError):
        RelationWeights(semantic=-1.0, spelling=1.0, coerror=1.0, temporal=0.0)
