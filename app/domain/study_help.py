"""Deterministic grounding for small-model help shown beside a word card."""

from __future__ import annotations

import re

from app.domain.acquisition import mask_target_forms

_MEMORY_QUESTION_MARKERS = (
    "怎么记",
    "如何记",
    "记忆",
    "记住",
    "记不住",
    "助记",
    "mnemonic",
)
_CONTEXT_FIELDS = frozenset(
    ("word", "meaning", "example", "collocations", "word_family")
)
_REQUIRED_CONTEXT_FIELDS = frozenset(("word", "meaning"))
_SCENE_PREFIX = re.compile(r"^场景联想\s*[：:]\s*(.*)$")


def is_memory_help_question(question: str) -> bool:
    normalized = question.casefold()
    return any(marker in normalized for marker in _MEMORY_QUESTION_MARKERS)


def build_deterministic_memory_answer(
    question: str,
    context: str | None,
) -> str | None:
    """Build an instant memory card exclusively from supplied card facts."""
    if not context or not is_memory_help_question(question):
        return None
    fields = _parse_card_context(context)
    if not _REQUIRED_CONTEXT_FIELDS.issubset(fields):
        return None
    word = fields["word"]
    meaning = fields["meaning"]
    if not word or not meaning:
        return None

    example = fields.get("example", "")
    collocations = _context_items(fields.get("collocations", ""))[:2]
    word_family = _context_items(fields.get("word_family", ""))[:2]
    if collocations:
        collocation_line = "；".join(collocations)
    elif example:
        collocation_line = "词卡暂无可靠固定搭配；先用例句建立词义联系。"
    else:
        collocation_line = "词卡暂无可靠固定搭配。"

    if example:
        cloze = mask_target_forms(word, example)
        example_line = (
            f"{cloze}（提示：{meaning}）"
            if cloze != example
            else f"{example}（词卡例句未找到可安全挖空的目标词形）"
        )
    else:
        example_line = "词卡暂无可用例句；先做中文义到英文拼写回忆。"
    family_line = (
        "；".join(word_family) if word_family else "暂无可靠词族条目，避免牵强联想。"
    )
    return (
        "快速助记（程序生成，不调用模型）\n"
        f"核心义：{word} = {meaning}\n"
        f"搭配锚点：{collocation_line}\n"
        f"例句回忆：{example_line}\n"
        f"词族串联：{family_line}\n"
        f"10 秒自测：{meaning} → ____（写出英文单词）"
    )


def ground_contextual_memory_answer(
    question: str,
    context: str | None,
    model_answer: str,
) -> str:
    """Keep the model's scene but derive learning material from card facts."""
    if not context or not is_memory_help_question(question):
        return model_answer

    fields = _parse_card_context(context)
    if not _REQUIRED_CONTEXT_FIELDS.issubset(fields):
        return model_answer
    word = fields["word"]
    meaning = fields["meaning"]
    example = fields.get("example", "")
    if not word or not meaning:
        return model_answer

    if example:
        cloze = mask_target_forms(word, example)
        if cloze == example:
            return model_answer
        hook = f"“{example}” = {meaning}"
        recall = f"“{cloze}”（提示：{meaning}）"
    else:
        hook = f"“{word}” = {meaning}"
        recall = f"{meaning} → ____（写出英文单词）"

    scene = _extract_scene(model_answer)
    if not scene:
        scene = (
            f"把词卡例句“{example}”想象成一个连续发生的动作场景。"
            if example
            else f"想象一个能表现“{meaning}”的人物、动作和结果。"
        )
    warning_source = "例句" if example else "已保存词义"

    return (
        f"记忆钩子：{hook}\n"
        f"场景联想：{scene}\n"
        f"主动回忆：{recall}\n"
        f"误区提醒：这是基于{warning_source}的联想，不是词源；"
        "先掌握词卡中的已保存词义，"
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


def _context_items(value: str) -> tuple[str, ...]:
    return tuple(
        item.strip() for item in re.split(r"\s+;\s+|；", value) if item.strip()
    )


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
