"""Deterministic, explainable routing for the scoped vocabulary assistant."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import Enum

_ENGLISH_TOKEN = re.compile(r"[a-z]+(?:[-'][a-z]+)*")

_LEARNING_MARKERS = (
    "cet",
    "四级",
    "六级",
    "英语",
    "英文",
    "翻译",
    "单词",
    "词汇",
    "词义",
    "什么意思",
    "区别",
    "辨析",
    "语法",
    "例句",
    "搭配",
    "用法",
    "怎么用",
    "发音",
    "音标",
    "怎么记",
    "记忆",
    "同义词",
    "反义词",
    "时态",
    "从句",
    "虚拟语气",
    "meaning",
    "mean",
    "difference",
    "grammar",
    "example",
    "usage",
    "pronounce",
    "pronunciation",
    "phonetic",
    "memorize",
    "synonym",
    "antonym",
    "vocabulary",
    "word",
    "translate",
    "tense",
)

_OUT_OF_SCOPE_MARKERS = (
    "天气预报",
    "股票行情",
    "股票价格",
    "股价",
    "写代码",
    "编程实现",
    "旅游攻略",
    "旅行计划",
    "菜谱",
    "政治新闻",
    "实时新闻",
    "医疗诊断",
    "法律意见",
    "weather forecast",
    "stock quote",
    "stock price",
    "write code",
    "travel itinerary",
    "recipe",
    "political news",
    "medical diagnosis",
    "legal advice",
)

_ADVANCED_TASK_MARKERS = (
    "整篇",
    "逐句",
    "全文",
    "长文",
    "学术论文",
    "文学翻译",
    "详细分析",
    "深度分析",
    "润色",
    "改写",
    "whole article",
    "full article",
    "line by line",
    "academic paper",
    "literary translation",
    "proofread",
    "rewrite",
)


class QueryRoute(str, Enum):
    LOCAL = "local"
    CONFIRM_ADVANCED = "confirm_advanced"
    REFUSE = "refuse"


@dataclass(frozen=True, slots=True)
class QueryAssessment:
    route: QueryRoute
    confidence: float
    reason: str


@dataclass(frozen=True, slots=True)
class QueryRoutingPolicy:
    max_local_characters: int = 220
    max_local_english_tokens: int = 40

    def __post_init__(self) -> None:
        if self.max_local_characters <= 0 or self.max_local_english_tokens <= 0:
            raise ValueError("Query routing limits must be positive")

    def assess(self, question: str) -> QueryAssessment:
        normalized = _normalize(question)
        if not normalized:
            return QueryAssessment(QueryRoute.REFUSE, 1.0, "问题为空。")

        english_tokens = _ENGLISH_TOKEN.findall(normalized)
        has_learning_context = _contains_any(normalized, _LEARNING_MARKERS)
        has_explicit_off_topic = _contains_any(normalized, _OUT_OF_SCOPE_MARKERS)
        looks_like_headword_or_phrase = 1 <= len(english_tokens) <= 3

        if has_explicit_off_topic and not has_learning_context:
            return QueryAssessment(
                QueryRoute.REFUSE,
                0.98,
                "问题属于词汇学习范围之外的实时或专业任务。",
            )

        if not has_learning_context and not looks_like_headword_or_phrase:
            return QueryAssessment(
                QueryRoute.REFUSE,
                0.86,
                "没有识别到四六级词汇、基础语法或英语学习意图。",
            )

        if len(normalized) > self.max_local_characters:
            return QueryAssessment(
                QueryRoute.CONFIRM_ADVANCED,
                0.42,
                "问题较长，本地小模型可能无法稳定覆盖全部细节。",
            )

        if len(english_tokens) > self.max_local_english_tokens or _contains_any(
            normalized, _ADVANCED_TASK_MARKERS
        ):
            return QueryAssessment(
                QueryRoute.CONFIRM_ADVANCED,
                0.46,
                "问题包含长文本或高复杂度语言任务。",
            )

        confidence = 0.9 if has_learning_context else 0.76
        return QueryAssessment(
            QueryRoute.LOCAL,
            confidence,
            "问题适合由本地词汇模型回答。",
        )


def _normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _contains_any(value: str, markers: tuple[str, ...]) -> bool:
    return any(marker in value for marker in markers)
