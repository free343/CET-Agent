from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from sqlalchemy import func, select

from app.ai.llm_provider import LLMProvider, LLMUnavailableError
from app.ai.schemas import ClusterAnalysis
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

    def generate(self, messages, response_schema=None) -> str:
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
