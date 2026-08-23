"""Model-backed explanations with validation, routing, and cache safety."""

from __future__ import annotations

import json
import logging
from collections import Counter
from collections.abc import Sequence

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from app.ai.conversation import ChatExchange
from app.ai.llm_provider import LLMProvider, LLMUnavailableError
from app.ai.prompts import PROMPT_VERSION, chat_messages, cluster_analysis_messages
from app.ai.schemas import (
    MAX_CHAT_RESPONSE_CHARS,
    MAX_CLUSTER_RESPONSE_CHARS,
    AIAnswer,
    ClusterAnalysis,
    ClusterAnalysisResult,
    Exercise,
    WordExplanation,
)
from app.db.database import Database
from app.db.models import AIAnalysis
from app.db.repositories import AIAnalysisRepository
from app.domain.query_routing import (
    QueryAssessment,
    QueryRoute,
    QueryRoutingPolicy,
    is_lexical_expansion_question,
)
from app.domain.study_help import (
    build_deterministic_memory_answer,
    ground_contextual_memory_answer,
)
from app.services.analysis_service import ConfusionCluster
from app.utils.text_utils import stable_json_hash

logger = logging.getLogger(__name__)


class AIService:
    def __init__(
        self,
        database: Database,
        local_provider: LLMProvider,
        advanced_provider: LLMProvider | None = None,
        routing_policy: QueryRoutingPolicy | None = None,
    ) -> None:
        self.database = database
        self.local_provider = local_provider
        self.advanced_provider = advanced_provider
        self.routing_policy = routing_policy or QueryRoutingPolicy()

    @property
    def advanced_available(self) -> bool:
        return self.advanced_provider is not None

    @property
    def local_model_name(self) -> str:
        return self.local_provider.model

    @property
    def advanced_model_name(self) -> str | None:
        if self.advanced_provider is None:
            return None
        return self.advanced_provider.model

    def route_question(self, question: str) -> QueryAssessment:
        return self.routing_policy.assess(question)

    def ask(
        self,
        question: str,
        *,
        use_advanced: bool = False,
        history: Sequence[ChatExchange] = (),
        context: str | None = None,
    ) -> AIAnswer:
        assessment = self.route_question(question)
        if assessment.route is QueryRoute.REFUSE:
            return AIAnswer(
                text="我只回答四六级词汇、基础英语语法、词义辨析和记忆技巧相关问题。",
                confidence=assessment.confidence,
                model="scope-policy",
            )
        if not use_advanced:
            deterministic_memory = build_deterministic_memory_answer(
                question,
                context,
            )
            if deterministic_memory is not None:
                return AIAnswer(
                    text=self._bounded_chat_text(deterministic_memory),
                    confidence=1.0,
                    model="deterministic-memory",
                )
        provider = self.advanced_provider if use_advanced else self.local_provider
        if provider is None:
            return AIAnswer(
                text="高级模型尚未配置。请在 .env 中配置 Provider 后再试。",
                confidence=assessment.confidence,
                model="unconfigured",
                degraded=True,
            )
        try:
            generated = provider.generate(
                chat_messages(
                    question,
                    history,
                    context=context,
                    allow_external_lexical_knowledge=use_advanced,
                )
            )
            text = ground_contextual_memory_answer(question, context, generated)
            if use_advanced and is_lexical_expansion_question(question):
                text = f"高级模型补充（未经过当前词卡人工审核）：\n{text}"
            return AIAnswer(
                text=self._bounded_chat_text(text),
                confidence=assessment.confidence,
                model=provider.model,
            )
        except LLMUnavailableError as exc:
            logger.warning("Vocabulary assistant unavailable: %s", exc)
            message = str(exc).strip() or "模型服务暂不可用，请稍后重试。"
            return AIAnswer(
                text=self._bounded_chat_text(message),
                confidence=assessment.confidence,
                model=provider.model,
                degraded=True,
            )

    def analyze_cluster(self, cluster: ConfusionCluster) -> ClusterAnalysisResult:
        payload = {
            "words": list(cluster.words),
            "statistics": {
                f"{word}_errors": count
                for word, count in zip(cluster.words, cluster.error_counts, strict=True)
            },
            "relation": {
                "type": cluster.relation_type.value,
                "average_score": round(cluster.average_score, 4),
            },
            "prompt_version": PROMPT_VERSION,
            "provider": {
                "type": type(self.local_provider).__name__,
                "model": self.local_provider.model,
                "base_url": str(getattr(self.local_provider, "base_url", "local")),
            },
        }
        content_hash = stable_json_hash(payload)
        with self.database.session() as session:
            cached = AIAnalysisRepository(session).get_cached(
                "confusion_cluster", content_hash
            )
            if cached:
                try:
                    if len(cached.output_json) > MAX_CLUSTER_RESPONSE_CHARS:
                        raise ValueError("Cached cluster analysis exceeds size budget")
                    analysis = ClusterAnalysis.model_validate_json(cached.output_json)
                    self._validate_cluster_words(analysis, cluster)
                    return ClusterAnalysisResult(
                        analysis=analysis,
                        confidence=0.9,
                        cached=True,
                        model=cached.model,
                    )
                except (ValidationError, ValueError):
                    logger.warning(
                        "Ignoring invalid cached cluster analysis id=%s", cached.id
                    )
                    session.delete(cached)

        for attempt in range(2):
            try:
                raw = self.local_provider.generate(
                    cluster_analysis_messages(payload, retry=attempt == 1),
                    ClusterAnalysis,
                )
                analysis = self._parse_cluster_analysis(raw)
                self._validate_cluster_words(analysis, cluster)
                try:
                    with self.database.session() as session:
                        AIAnalysisRepository(session).add(
                            AIAnalysis(
                                analysis_type="confusion_cluster",
                                content_hash=content_hash,
                                input_json=json.dumps(
                                    payload,
                                    ensure_ascii=False,
                                    sort_keys=True,
                                ),
                                output_json=analysis.model_dump_json(),
                                model=self.local_provider.model,
                            )
                        )
                except IntegrityError:
                    # Another window generated and stored the same analysis
                    # after our initial cache read. Treat that winner as a
                    # cache hit instead of surfacing a unique-key error.
                    with self.database.session() as session:
                        cached = AIAnalysisRepository(session).get_cached(
                            "confusion_cluster",
                            content_hash,
                        )
                        if cached is None:
                            raise
                        cached_analysis = ClusterAnalysis.model_validate_json(
                            cached.output_json
                        )
                        self._validate_cluster_words(cached_analysis, cluster)
                        return ClusterAnalysisResult(
                            analysis=cached_analysis,
                            confidence=0.9,
                            cached=True,
                            model=cached.model,
                        )
                logger.info(
                    "Cluster analysis completed words=%s", ",".join(cluster.words)
                )
                return ClusterAnalysisResult(
                    analysis=analysis,
                    confidence=0.88,
                    model=self.local_provider.model,
                )
            except (ValidationError, ValueError) as exc:
                logger.warning(
                    "Invalid cluster JSON attempt=%s error=%s", attempt + 1, exc
                )
            except LLMUnavailableError as exc:
                logger.warning("Cluster model unavailable: %s", exc)
                return self._fallback(cluster, str(exc))
        return self._fallback(cluster, "模型输出未通过结构校验，请稍后重试。")

    @staticmethod
    def _parse_cluster_analysis(raw: str) -> ClusterAnalysis:
        if len(raw) > MAX_CLUSTER_RESPONSE_CHARS:
            raise ValueError("Cluster analysis exceeds size budget")
        content = raw.strip()
        if content.startswith("```"):
            lines = content.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            content = "\n".join(lines)
        return ClusterAnalysis.model_validate_json(content)

    @staticmethod
    def _bounded_chat_text(value: str) -> str:
        if len(value) <= MAX_CHAT_RESPONSE_CHARS:
            return value
        return value[: MAX_CHAT_RESPONSE_CHARS - 1].rstrip() + "…"

    @staticmethod
    def _validate_cluster_words(
        analysis: ClusterAnalysis,
        cluster: ConfusionCluster,
    ) -> None:
        expected = Counter(word.strip().casefold() for word in cluster.words)
        actual = Counter(
            item.word.strip().casefold() for item in analysis.word_explanations
        )
        if actual != expected:
            raise ValueError(
                "Cluster analysis must explain every input word exactly once"
            )

    def _fallback(
        self, cluster: ConfusionCluster, reason: str
    ) -> ClusterAnalysisResult:
        analysis = ClusterAnalysis(
            summary="暂时无法生成个性化 AI 分析。确定性错词关系仍然可用。",
            confusion_reason=reason,
            word_explanations=[
                WordExplanation(
                    word=word,
                    meaning="请查看词库中的已保存释义。",
                    usage="本地模型恢复后可生成用法辨析。",
                    memory_tip="先比较拼写差异，再结合例句回忆。",
                    example="",
                )
                for word in cluster.words
            ],
            exercise=Exercise(
                question="本地模型恢复后可生成针对性练习。",
                options=[],
                answer="",
                explanation="",
            ),
        )
        return ClusterAnalysisResult(
            analysis=analysis,
            confidence=0.0,
            model=self.local_provider.model,
            degraded=True,
        )
