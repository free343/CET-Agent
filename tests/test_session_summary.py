from __future__ import annotations

from datetime import datetime

from app.ui.session_summary import (
    format_acquisition_summary,
    format_review_summary,
)
from app.utils.datetime_utils import UTC


def test_review_summary_is_pure_and_distinguishes_practice() -> None:
    due = datetime(2026, 8, 25, 9, tzinfo=UTC)

    formal = format_review_summary(2, 1, 1, [due], practice=False)
    practice = format_review_summary(2, 1, 1, [due], practice=True)

    assert "最早复习" in formal
    assert "答对 1，需加强 1" in formal
    assert practice == "本轮完成 2 个：想起 1，没想起 1。"


def test_acquisition_summary_contains_stage_counts_and_first_due() -> None:
    summary = format_acquisition_summary(
        3,
        1,
        1,
        {0: 1, 2: 2},
        {2: 1},
        datetime(2026, 8, 25, 9, tzinfo=UTC),
    )

    assert "本轮尝试 3 次，错误 1 次" in summary
    assert "阶段2 2次/1错" in summary
    assert "新毕业 1 个" in summary
    assert "首个正式复习" in summary
