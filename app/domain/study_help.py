"""Deterministic grounding for small-model help shown beside a word card."""

from __future__ import annotations

import re

_MEMORY_QUESTION_MARKERS = (
    "怎么记",
    "如何记",
    "记忆",
    "记住",
    "记不住",
    "助记",
    "mnemonic",
)
_CONTEXT_FIELDS = frozenset(("word", "meaning", "example"))
_SCENE_PREFIX = re.compile(r"^场景联想\s*[：:]\s*(.*)$")


def is_memory_help_question(question: str) -> bool:
    normalized = question.casefold()
    return any(marker in normalized for marker in _MEMORY_QUESTION_MARKERS)


def ground_contextual_memory_answer(
    question: str,
    context: str | None,
    model_answer: str,
) -> str:
    """Keep the model's scene but derive learning material from card facts."""
    if not context or not is_memory_help_question(question):
        return model_answer

    fields = _parse_card_context(context)
    if fields.keys() != _CONTEXT_FIELDS:
        return model_answer
    word = fields["word"]
    meaning = fields["meaning"]
    example = fields["example"]
    if not word or not meaning or not example:
        return model_answer

    word_pattern = re.compile(
        rf"(?<![A-Za-z]){re.escape(word)}(?![A-Za-z])",
        flags=re.IGNORECASE,
    )
    cloze, replacements = word_pattern.subn("____", example, count=1)
    if replacements != 1:
        return model_answer

    scene = _extract_scene(model_answer)
    if not scene:
        scene = f"把词卡例句“{example}”想象成一个连续发生的动作场景。"

    return (
        f"记忆钩子：“{example}” = {meaning}\n"
        f"场景联想：{scene}\n"
        f"主动回忆：“{cloze}”（提示：{meaning}）\n"
        "误区提醒：这是一条例句联想，不是词源；先掌握词卡中的已保存词义，"
        "其他义项再用独立例句巩固。"
    )


def _parse_card_context(context: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in context.splitlines():
        key, separator, value = line.partition("=")
        normalized_key = key.strip().casefold()
        if separator and normalized_key in _CONTEXT_FIELDS:
            fields[normalized_key] = value.strip()
    return fields


def _extract_scene(model_answer: str) -> str:
    lines = model_answer.splitlines()
    for index, line in enumerate(lines):
        match = _SCENE_PREFIX.match(line.strip())
        if match is None:
            continue
        scene = match.group(1).strip()
        if not scene:
            scene = next(
                (
                    candidate.strip()
                    for candidate in lines[index + 1 :]
                    if candidate.strip()
                ),
                "",
            )
        return scene[:300]
    return ""
