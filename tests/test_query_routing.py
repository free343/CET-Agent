from __future__ import annotations

import pytest

from app.domain.query_routing import QueryRoute, QueryRoutingPolicy

POLICY = QueryRoutingPolicy()


@pytest.mark.parametrize(
    "question",
    (
        "economic 和 economical 有什么区别？",
        "这个词容易和哪些词混淆？",
        "现在完成时怎么用？",
        "adapt",
        "What does complement mean?",
        "ＣＥＴ４ 单词怎么记？",
        "股票行情这个短语是什么意思？",
    ),
)
def test_vocabulary_and_basic_grammar_questions_use_local_model(question) -> None:
    assessment = POLICY.assess(question)

    assert assessment.route is QueryRoute.LOCAL
    assert assessment.confidence >= 0.75


@pytest.mark.parametrize(
    "question",
    (
        "帮我查今天的股票行情",
        "给我制定一份旅行计划",
        "Please give me a weather forecast",
        "Tell me a joke about robots",
        "Tell me a meaningful joke",
        "I forgot my password",
        "请用英语写代码",
        "",
    ),
)
def test_out_of_scope_or_empty_questions_are_refused(question) -> None:
    assessment = POLICY.assess(question)

    assert assessment.route is QueryRoute.REFUSE
    assert assessment.confidence >= 0.85


def test_long_or_complex_language_task_requires_explicit_model_choice() -> None:
    long_question = "请解释 adapt 的用法并逐句分析这些例句：" + "adapt to change. " * 30

    length_assessment = POLICY.assess(long_question)
    task_assessment = POLICY.assess("请逐句分析这篇 academic paper 的 vocabulary")
    translation_assessment = POLICY.assess("请帮我做这篇文章的文学翻译")

    assert length_assessment.route is QueryRoute.CONFIRM_ADVANCED
    assert "较长" in length_assessment.reason
    assert task_assessment.route is QueryRoute.CONFIRM_ADVANCED
    assert translation_assessment.route is QueryRoute.CONFIRM_ADVANCED


@pytest.mark.parametrize(
    "question",
    (
        "main 有什么近义词？",
        "请给出 important 的同义词",
        "What are the antonyms of primary?",
        "What are the synonyms of stock price?",
    ),
)
def test_lexical_expansion_requires_explicit_advanced_choice(question: str) -> None:
    assessment = POLICY.assess(question)

    assert assessment.route is QueryRoute.CONFIRM_ADVANCED
    assert "词卡之外" in assessment.reason


def test_explicit_off_topic_policy_takes_priority_over_length() -> None:
    question = "请给我天气预报。" + "明天是否下雨？" * 100

    assert POLICY.assess(question).route is QueryRoute.REFUSE


def test_policy_rejects_invalid_limits() -> None:
    with pytest.raises(ValueError):
        QueryRoutingPolicy(max_local_characters=0)
    with pytest.raises(ValueError):
        QueryRoutingPolicy(max_local_characters=500, max_question_characters=400)


def test_absolute_question_budget_refuses_oversized_input() -> None:
    assessment = POLICY.assess("adapt " * 1_000)

    assert assessment.route is QueryRoute.REFUSE
    assert assessment.confidence == 1.0
    assert "过长" in assessment.reason
