"""SQLAlchemy models for vocabulary learning and AI analysis data."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SqlEnum,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from app.utils.datetime_utils import UTC, ensure_utc, utc_now


class UTCDateTime(TypeDecorator[datetime]):
    """Persist UTC as naive SQLite values and restore an aware UTC datetime."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(
        self, value: datetime | None, dialect: Any
    ) -> datetime | None:
        if value is None:
            return None
        return ensure_utc(value).replace(tzinfo=None)

    def process_result_value(
        self, value: datetime | None, dialect: Any
    ) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class Base(DeclarativeBase):
    pass


class WordLevel(str, Enum):
    CET4 = "CET4"
    CET6 = "CET6"


class RelationType(str, Enum):
    SPELLING = "SPELLING"
    SEMANTIC = "SEMANTIC"
    CO_ERROR = "CO_ERROR"
    TEMPORAL = "TEMPORAL"
    MIXED = "MIXED"


class Word(Base):
    __tablename__ = "words"

    id: Mapped[int] = mapped_column(primary_key=True)
    word: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    phonetic: Mapped[str] = mapped_column(String(200), default="")
    meaning: Mapped[str] = mapped_column(Text)
    example: Mapped[str] = mapped_column(Text, default="")
    level: Mapped[WordLevel] = mapped_column(SqlEnum(WordLevel, native_enum=False))
    frequency: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)

    learning_state: Mapped[LearningState | None] = relationship(
        back_populates="word", cascade="all, delete-orphan", uselist=False
    )
    review_logs: Mapped[list[ReviewLog]] = relationship(
        back_populates="word", cascade="all, delete-orphan"
    )


class LearningState(Base):
    __tablename__ = "learning_states"
    __table_args__ = (
        CheckConstraint("fsrs_state BETWEEN 1 AND 3", name="ck_fsrs_state"),
        CheckConstraint("fsrs_step IS NULL OR fsrs_step >= 0", name="ck_fsrs_step"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    word_id: Mapped[int] = mapped_column(
        ForeignKey("words.id", ondelete="CASCADE"), unique=True, index=True
    )
    difficulty: Mapped[float] = mapped_column(Float, default=5.0)
    stability: Mapped[float] = mapped_column(Float, default=0.4)
    last_review_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True
    )
    next_review_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, index=True
    )
    review_count: Mapped[int] = mapped_column(Integer, default=0)
    correct_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    lapse_count: Mapped[int] = mapped_column(Integer, default=0)
    fsrs_state: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    fsrs_step: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=0, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now
    )

    word: Mapped[Word] = relationship(back_populates="learning_state")


class ReviewLog(Base):
    __tablename__ = "review_logs"
    __table_args__ = (
        CheckConstraint("rating BETWEEN 1 AND 4", name="ck_review_rating"),
        CheckConstraint("response_time_ms >= 0", name="ck_response_time"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    word_id: Mapped[int] = mapped_column(
        ForeignKey("words.id", ondelete="CASCADE"), index=True
    )
    reviewed_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    rating: Mapped[int] = mapped_column(Integer)
    is_correct: Mapped[bool] = mapped_column(Boolean)
    response_time_ms: Mapped[int] = mapped_column(Integer, default=0)
    question_type: Mapped[str] = mapped_column(String(50), default="meaning_recall")
    user_answer: Mapped[str] = mapped_column(Text, default="")
    previous_stability: Mapped[float] = mapped_column(Float)
    new_stability: Mapped[float] = mapped_column(Float)
    previous_difficulty: Mapped[float] = mapped_column(Float)
    new_difficulty: Mapped[float] = mapped_column(Float)
    previous_last_review_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True
    )
    previous_next_review_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True
    )
    previous_fsrs_state: Mapped[int | None] = mapped_column(Integer, nullable=True)
    previous_fsrs_step: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scheduled_days: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)

    word: Mapped[Word] = relationship(back_populates="review_logs")


class FavoriteWord(Base):
    """A single-user personal wordbook entry."""

    __tablename__ = "favorite_words"

    word_id: Mapped[int] = mapped_column(
        ForeignKey("words.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)

    word: Mapped[Word] = relationship()


class ConfusionEdge(Base):
    __tablename__ = "confusion_edges"
    __table_args__ = (
        CheckConstraint("word_a_id < word_b_id", name="ck_edge_order"),
        UniqueConstraint("word_a_id", "word_b_id", name="uq_confusion_pair"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    word_a_id: Mapped[int] = mapped_column(
        ForeignKey("words.id", ondelete="CASCADE"), index=True
    )
    word_b_id: Mapped[int] = mapped_column(
        ForeignKey("words.id", ondelete="CASCADE"), index=True
    )
    semantic_score: Mapped[float] = mapped_column(Float, default=0.0)
    spelling_score: Mapped[float] = mapped_column(Float, default=0.0)
    coerror_score: Mapped[float] = mapped_column(Float, default=0.0)
    temporal_score: Mapped[float] = mapped_column(Float, default=0.0)
    total_score: Mapped[float] = mapped_column(Float, index=True)
    relation_type: Mapped[RelationType] = mapped_column(
        SqlEnum(RelationType, native_enum=False)
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now
    )

    word_a: Mapped[Word] = relationship(foreign_keys=[word_a_id])
    word_b: Mapped[Word] = relationship(foreign_keys=[word_b_id])


class AIAnalysis(Base):
    __tablename__ = "ai_analyses"
    __table_args__ = (
        UniqueConstraint("analysis_type", "content_hash", name="uq_ai_cache"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_type: Mapped[str] = mapped_column(String(50), index=True)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    input_json: Mapped[str] = mapped_column(Text)
    output_json: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class EmbeddingCache(Base):
    __tablename__ = "embedding_cache"
    __table_args__ = (
        UniqueConstraint("model", "content_hash", name="uq_embedding_cache"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    model: Mapped[str] = mapped_column(String(200))
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    source_text: Mapped[str] = mapped_column(Text)
    vector_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class StudyLevelActivation(Base):
    """Persist the first real activation of each independently staged level."""

    __tablename__ = "study_level_activations"
    __table_args__ = (
        CheckConstraint(
            "rebased_word_count >= 0",
            name="ck_level_activation_rebased_count",
        ),
    )

    level: Mapped[WordLevel] = mapped_column(
        SqlEnum(WordLevel, native_enum=False),
        primary_key=True,
    )
    activated_at: Mapped[datetime] = mapped_column(UTCDateTime())
    schedule_rebased: Mapped[bool] = mapped_column(Boolean, default=False)
    rebased_word_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class ReminderRuntimeState(Base):
    """Single-user persisted reminder cooldown and completion state."""

    __tablename__ = "reminder_runtime_state"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    last_notification_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True
    )
    last_snooze_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True
    )
    completed_local_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now
    )


class ReminderReviewLease(Base):
    """Per-process lease used to suppress reminders during active reviews."""

    __tablename__ = "reminder_review_leases"

    owner_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    lease_until: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now
    )
