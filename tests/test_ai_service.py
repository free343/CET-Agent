from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from app.ai.llm_provider import LLMProvider, LLMUnavailableError
from app.ai.schemas import MAX_CHAT_RESPONSE_CHARS, ClusterAnalysis
from app.db.models import AIAnalysis, RelationType
from app.services.ai_service import AIService
from app.services.analysis_service import ConfusionCluster

VALID_ANALYSIS = {
    "summary": "这些词拼写相近，但词性和含义不同。",
    "confusion_reason": "中间元音变化小，视觉形态接近。",
    "word_explanations": [
        {
            "word": "adapt",
            "meaning": "适应；改编",
            "usage": "adapt to something",
            "memory_tip": "adapt 的 a 联想 adjust",
            "example": "We adapt to change.",
        },
        {
            "word": "adopt",
            "meaning": "采用；收养",
            "usage": "adopt a method",
            "memory_tip": "adopt 中的 o 联想 offer a home",
            "example": "They adopted a new plan.",
        },
    ],
    "exercise": {
        "question": "We should ___ to the new rules.",
        "options": ["A. adapt", "B. adopt"],
        "answer": "A. adapt",
        "explanation": "adapt to 表示适应。",
    },
}


class FakeProvider(LLMProvider):
    model = "fake-3b"

    def __init__(self, responses: list[str], model: str = "fake-3b") -> None:
        self.responses = responses
        self.model = model
        self.calls = 0
        self.messages = []

    def generate(self, messages, response_schema=None) -> str:
        self.messages.append(messages)
        response = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        return response


class UnavailableProvider(LLMProvider):
    model = "offline-3b"

    def generate(self, messages, response_schema=None) -> str:
        raise LLMUnavailableError("本地模型未运行")


class BarrierProvider(LLMProvider):
    model = "concurrent-3b"

    def __init__(self, barrier: Barrier) -> None:
        self.barrier = barrier

    def generate(self, messages, response_schema=None) -> str:
        self.barrier.wait(timeout=5)
        return json.dumps(VALID_ANALYSIS, ensure_ascii=False)


def sample_cluster() -> ConfusionCluster:
    return ConfusionCluster(
        cluster_number=1,
        word_ids=(1, 2),
        words=("adapt", "adopt"),
        error_counts=(5, 4),
        relation_type=RelationType.SPELLING,
        average_score=0.83,
    )


def test_cluster_analysis_is_validated_and_cached(database) -> None:
    provider = FakeProvider([json.dumps(VALID_ANALYSIS, ensure_ascii=False)])
    service = AIService(database, provider)

    first = service.analyze_cluster(sample_cluster())
    second = service.analyze_cluster(sample_cluster())

    assert isinstance(first.analysis, ClusterAnalysis)
    assert first.cached is False
    assert second.cached is True
    assert provider.calls == 1
    with database.session() as session:
        assert session.scalar(select(func.count(AIAnalysis.id))) == 1


def test_invalid_json_retries_once_then_degrades(database) -> None:
    provider = FakeProvider(["not-json", "still-not-json"])
    result = AIService(database, provider).analyze_cluster(sample_cluster())
    assert provider.calls == 2
    assert result.degraded is True
    assert result.confidence == 0.0


def test_cluster_analysis_rejects_words_not_in_input_cluster(database) -> None:
    wrong_words = {
        **VALID_ANALYSIS,
        "word_explanations": [
            {**VALID_ANALYSIS["word_explanations"][0], "word": "intruder"},
            VALID_ANALYSIS["word_explanations"][1],
        ],
    }
    provider = FakeProvider(
        [
            json.dumps(wrong_words, ensure_ascii=False),
            json.dumps(VALID_ANALYSIS, ensure_ascii=False),
        ]
    )

    result = AIService(database, provider).analyze_cluster(sample_cluster())

    assert provider.calls == 2
    assert result.degraded is False
    assert {item.word for item in result.analysis.word_explanations} == {
        "adapt",
        "adopt",
    }


def test_out_of_scope_question_never_calls_model(database) -> None:
    provider = FakeProvider(["unused"])
    answer = AIService(database, provider).ask("帮我查一下今天的股票行情")
    assert provider.calls == 0
    assert "只回答" in answer.text


def test_vocabulary_question_about_off_topic_noun_still_calls_model(database) -> None:
    provider = FakeProvider(["stock 表示股票。"])

    answer = AIService(database, provider).ask("股票行情这个短语是什么意思？")

    assert provider.calls == 1
    assert answer.model == "fake-3b"


def test_explicit_advanced_choice_uses_independent_provider(database) -> None:
    local = FakeProvider(["local"], model="local-model")
    advanced = FakeProvider(["advanced"], model="advanced-model")
    service = AIService(database, local, advanced)

    answer = service.ask("请逐句分析这篇文章的词汇", use_advanced=True)

    assert service.advanced_available is True
    assert local.calls == 0
    assert advanced.calls == 1
    assert answer.text == "advanced"
    assert answer.model == "advanced-model"


def test_unavailable_model_returns_safe_cluster_fallback(database) -> None:
    result = AIService(database, UnavailableProvider()).analyze_cluster(
        sample_cluster()
    )
    assert result.degraded is True
    assert result.model == "offline-3b"
    assert "确定性错词关系仍然可用" in result.analysis.summary


def test_changing_model_does_not_reuse_previous_cache(database) -> None:
    first_provider = FakeProvider(
        [json.dumps(VALID_ANALYSIS, ensure_ascii=False)], model="model-a"
    )
    second_provider = FakeProvider(
        [json.dumps(VALID_ANALYSIS, ensure_ascii=False)], model="model-b"
    )

    AIService(database, first_provider).analyze_cluster(sample_cluster())
    second_result = AIService(database, second_provider).analyze_cluster(
        sample_cluster()
    )

    assert first_provider.calls == 1
    assert second_provider.calls == 1
    assert second_result.cached is False
    with database.session() as session:
        assert session.scalar(select(func.count(AIAnalysis.id))) == 2


def test_concurrent_cluster_analysis_cache_writes_converge(database) -> None:
    service = AIService(database, BarrierProvider(Barrier(2)))

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda _index: service.analyze_cluster(sample_cluster()), range(2))
        )

    assert sorted(result.cached for result in results) == [False, True]
    with database.session() as session:
        assert session.scalar(select(func.count(AIAnalysis.id))) == 1


def test_overlong_cluster_field_retries_then_degrades(database) -> None:
    oversized = deepcopy(VALID_ANALYSIS)
    oversized["summary"] = "x" * 1_201
    provider = FakeProvider([json.dumps(oversized), json.dumps(oversized)])

    result = AIService(database, provider).analyze_cluster(sample_cluster())

    assert provider.calls == 2
    assert result.degraded is True
    with database.session() as session:
        assert session.scalar(select(func.count(AIAnalysis.id))) == 0


def test_cluster_schema_rejects_excessive_options_and_words() -> None:
    excessive_options = deepcopy(VALID_ANALYSIS)
    excessive_options["exercise"]["options"] = [f"option-{index}" for index in range(7)]
    overlong_option = deepcopy(VALID_ANALYSIS)
    overlong_option["exercise"]["options"] = ["x" * 301]
    excessive_words = deepcopy(VALID_ANALYSIS)
    excessive_words["word_explanations"] *= 5

    with pytest.raises(ValidationError):
        ClusterAnalysis.model_validate(excessive_options)
    with pytest.raises(ValidationError):
        ClusterAnalysis.model_validate(overlong_option)
    with pytest.raises(ValidationError):
        ClusterAnalysis.model_validate(excessive_words)


def test_chat_answer_is_truncated_to_capacity_budget(database) -> None:
    provider = FakeProvider(["x" * (MAX_CHAT_RESPONSE_CHARS + 100)])

    answer = AIService(database, provider).ask("adapt 是什么意思？")

    assert len(answer.text) == MAX_CHAT_RESPONSE_CHARS
    assert answer.text.endswith("…")


def test_contextual_chat_passes_only_explicit_word_context(database) -> None:
    provider = FakeProvider(["adapt 可以联想 adjust。"])

    answer = AIService(database, provider).ask(
        "这个词怎么记？",
        context="word=adapt\nmeaning=适应；改编",
    )

    assert answer.degraded is False
    prompt = provider.messages[0][-1]["content"]
    assert "word=adapt" in prompt
    assert "meaning=适应；改编" in prompt
    assert "这个词怎么记？" in prompt
