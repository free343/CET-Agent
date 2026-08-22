"""Validated structured outputs returned by vocabulary analysis."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

MAX_CHAT_RESPONSE_CHARS = 4_000
MAX_CLUSTER_RESPONSE_CHARS = 32_000
ExerciseOption = Annotated[str, Field(max_length=300)]


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
