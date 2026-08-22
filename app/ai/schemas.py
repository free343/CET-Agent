"""Validated structured outputs returned by vocabulary analysis."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

MAX_CHAT_RESPONSE_CHARS = 4_000
MAX_CLUSTER_RESPONSE_CHARS = 32_000
ExerciseOption = Annotated[str, Field(max_length=300)]

WORD_LEARNING_AIDS_PROMPT_VERSION = "word-learning-aids-v1"
MAX_EXAMPLE_CHARS = 160
MAX_EXAMPLE_TRANSLATION_CHARS = 240
MAX_COLLOCATION_FIELD_CHARS = 80
MAX_WORD_FAMILY_WORD_CHARS = 100
MAX_WORD_FAMILY_MEANING_CHARS = 120
MAX_WORD_FAMILY_POS_CHARS = 20


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WordExplanation(StrictSchema):
    word: str = Field(max_length=100)
    meaning: str = Field(max_length=500)
    usage: str = Field(max_length=800)
    memory_tip: str = Field(max_length=800)
    example: str = Field(max_length=500)


class Exercise(StrictSchema):
    question: str = Field(max_length=600)
    options: list[ExerciseOption] = Field(default_factory=list, max_length=6)
    answer: str = Field(max_length=300)
    explanation: str = Field(max_length=1_200)


class ClusterAnalysis(StrictSchema):
    summary: str = Field(max_length=1_200)
    confusion_reason: str = Field(max_length=1_600)
    word_explanations: list[WordExplanation] = Field(min_length=1, max_length=8)
    exercise: Exercise


class ClusterAnalysisResult(StrictSchema):
    analysis: ClusterAnalysis
    confidence: float = Field(ge=0.0, le=1.0)
    cached: bool = False
    model: str = Field(max_length=200)
    degraded: bool = False


class AIAnswer(StrictSchema):
    text: str = Field(min_length=1, max_length=MAX_CHAT_RESPONSE_CHARS)
    confidence: float = Field(ge=0.0, le=1.0)
    model: str = Field(max_length=200)
    degraded: bool = False


class Collocation(StrictSchema):
    """A bounded fixed collocation with a concise Chinese meaning."""

    phrase: str = Field(min_length=1, max_length=MAX_COLLOCATION_FIELD_CHARS)
    meaning: str = Field(min_length=1, max_length=MAX_COLLOCATION_FIELD_CHARS)


class WordFamilyMember(StrictSchema):
    """A real morphological base or derivative of the target word."""

    word: str = Field(min_length=1, max_length=MAX_WORD_FAMILY_WORD_CHARS)
    part_of_speech: str = Field(min_length=1, max_length=MAX_WORD_FAMILY_POS_CHARS)
    meaning: str = Field(min_length=1, max_length=MAX_WORD_FAMILY_MEANING_CHARS)
    relation: Literal["base", "derivative"]


class WordLearningAidGeneration(StrictSchema):
    """One model-generated learning aid; assembled with source fields later."""

    word: str = Field(min_length=1, max_length=100)
    example: str = Field(min_length=1, max_length=MAX_EXAMPLE_CHARS)
    example_translation: str = Field(
        min_length=1, max_length=MAX_EXAMPLE_TRANSLATION_CHARS
    )
    collocations: list[Collocation] = Field(min_length=2, max_length=4)
    word_family: list[WordFamilyMember] = Field(max_length=4)


class WordLearningAidGenerationBatch(StrictSchema):
    """The model's batch reply; the word multiset must match the request."""

    items: list[WordLearningAidGeneration]


class WordLearningAidGenerator(StrictSchema):
    provider: Literal["deepseek"]
    model: str = Field(min_length=1, max_length=200)
    prompt_version: Literal["word-learning-aids-v1"]


class WordLearningAidRecord(StrictSchema):
    """One fully assembled JSONL record matching the final artifact contract."""

    schema_version: Literal[1]
    word: str = Field(min_length=1, max_length=100)
    level: Literal["CET4", "CET6"]
    source_kind: Literal["curated", "open"]
    source_meaning: str = Field(min_length=1, max_length=500)
    example: str = Field(min_length=1, max_length=MAX_EXAMPLE_CHARS)
    example_translation: str = Field(
        min_length=1, max_length=MAX_EXAMPLE_TRANSLATION_CHARS
    )
    example_origin: Literal["curated", "ai_generated"]
    collocations: list[Collocation] = Field(min_length=2, max_length=4)
    word_family: list[WordFamilyMember] = Field(max_length=4)
    generator: WordLearningAidGenerator
    content_status: Literal["ai_generated_unreviewed"]
