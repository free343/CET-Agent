"""Pure formatting helpers for bounded study-session completion summaries."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime


def format_review_summary(
    completed: int,
    correct: int,
    wrong: int,
    review_due_times: Sequence[datetime],
    *,
    practice: bool,
) -> str:
    """Describe persisted review/practice outcomes without querying state."""

    if completed <= 0:
        return "本轮没有完成单词。"
    if practice:
        return f"本轮完成 {completed} 个：想起 {correct}，没想起 {wrong}。"
    next_due = min(review_due_times, default=None)
    due_text = (
        next_due.astimezone().strftime("%m-%d %H:%M")
        if next_due is not None
        else "稍后"
    )
    return (
        f"本轮完成 {completed} 个：答对 {correct}，需加强 {wrong}；"
        f"最早复习 {due_text}。"
    )


def format_acquisition_summary(
    attempts: int,
    mistakes: int,
    completed: int,
    stage_attempts: Mapping[int, int],
    stage_mistakes: Mapping[int, int],
    first_review_at: datetime | None,
) -> str:
    """Describe acquisition attempts, stage errors, and the first due time."""

    if attempts <= 0:
        return "本轮尚未记录学习尝试。"
    stage_parts = []
    for stage in (0, 1, 2):
        stage_count = stage_attempts.get(stage, 0)
        if stage_count:
            stage_parts.append(
                f"阶段{stage} {stage_count}次/{stage_mistakes.get(stage, 0)}错"
            )
    first_due = (
        first_review_at.astimezone().strftime("%m-%d %H:%M")
        if first_review_at is not None
        else "暂无"
    )
    stages = "，".join(stage_parts) if stage_parts else "暂无阶段明细"
    return (
        f"本轮尝试 {attempts} 次，错误 {mistakes} 次（{stages}）；"
        f"新毕业 {completed} 个，首个正式复习 {first_due}。"
    )
