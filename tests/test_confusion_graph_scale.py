from __future__ import annotations

from scripts.benchmark_confusion_graph import populate_dense_case, run_benchmark


def test_dense_max_candidate_graph_has_all_pairs(database) -> None:
    populate_dense_case(database)

    result = run_benchmark(database, iterations=1)

    assert result.candidate_count == 100
    assert result.edge_count == 4_950
    assert result.cluster_count == 1
    assert result.median_seconds > 0
