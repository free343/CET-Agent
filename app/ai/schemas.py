"""Validated structured outputs returned by vocabulary analysis."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WordExplanation(StrictSchema):
    word: str
    meaning: str
    usage: str
    memory_tip: str
    example: str


class Exercise(StrictSchema):
    question: str
    options: list[str] = Field(default_factory=list)
    answer: str
    explanation: str


class ClusterAnalysis(StrictSchema):
    summary: str
    confusion_reason: str
    word_explanations: list[WordExplanation]
    exercise: Exercise


class ClusterAnalysisResult(StrictSchema):
    analysis: ClusterAnalysis
    confidence: float = Field(ge=0.0, le=1.0)
    cached: bool = False
    model: str
    degraded: bool = False


class AIAnswer(StrictSchema):
    text: str
    confidence: float = Field(ge=0.0, le=1.0)
    model: str
    degraded: bool = False
