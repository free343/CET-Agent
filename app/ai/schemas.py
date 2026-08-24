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

# The lexical-fact artifact is deliberately separate from generated learning
# aids.  These limits are shared by the offline validator, database importer,
# deterministic query service, and UI projection.
LEXICAL_FACTS_PROMPT_VERSION = "lexical-facts-v1"
MAX_LEXICAL_FORM_CHARS = 80
MAX_LEXICAL_NOTE_CHARS = 240
MAX_LEXICAL_SENSE_CHARS = 160
MAX_LEXICAL_RELATION_CHARS = 80
MAX_LEXICAL_RELATION_MEANING_CHARS = 120
MAX_LEXICAL_RELATION_NOTE_CHARS = 240
MAX_LEXICAL_EVIDENCE_LOCATOR_CHARS = 200
MAX_LEXICAL_CANDIDATE_NOTE_CHARS = 240


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


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


class LexicalSurfaceForm(StrictSchema):
    """One attested surface form in a typed grammatical paradigm."""

    role: str = Field(min_length=1, max_length=40)
    value: str = Field(min_length=1, max_length=MAX_LEXICAL_FORM_CHARS)
    phonetic: str = Field(default="", max_length=120)
    region: str = Field(default="", max_length=40)
    usage_register: str = Field(
        default="",
        max_length=40,
        validation_alias="register",
        serialization_alias="register",
    )
    sense: str = Field(default="", max_length=MAX_LEXICAL_SENSE_CHARS)
    note: str = Field(default="", max_length=MAX_LEXICAL_NOTE_CHARS)

    @property
    def register(self) -> str:
        """Compatibility accessor using the compact contract name."""
        return self.usage_register


class NounParadigm(StrictSchema):
    paradigm_type: Literal["noun"]
    countability: Literal[
        "countable",
        "uncountable",
        "both",
        "plural_only",
        "invariant",
    ]
    forms: list[LexicalSurfaceForm] = Field(max_length=6)


class VerbParadigm(StrictSchema):
    paradigm_type: Literal["verb"]
    forms: list[LexicalSurfaceForm] = Field(max_length=8)


class DegreeParadigm(StrictSchema):
    paradigm_type: Literal["degree"]
    part_of_speech: Literal["adjective", "adverb"]
    gradability: Literal["gradable", "non_gradable", "contextual"]
    forms: list[LexicalSurfaceForm] = Field(max_length=8)


class NumeralParadigm(StrictSchema):
    paradigm_type: Literal["numeral"]
    forms: list[LexicalSurfaceForm] = Field(max_length=8)


class PronounParadigm(StrictSchema):
    paradigm_type: Literal["pronoun"]
    forms: list[LexicalSurfaceForm] = Field(max_length=8)


LexicalParadigm = Annotated[
    NounParadigm | VerbParadigm | DegreeParadigm | NumeralParadigm | PronounParadigm,
    Field(discriminator="paradigm_type"),
]


class LexicalRelationItem(StrictSchema):
    word: str = Field(min_length=1, max_length=MAX_LEXICAL_RELATION_CHARS)
    meaning: str = Field(
        min_length=1,
        max_length=MAX_LEXICAL_RELATION_MEANING_CHARS,
    )
    note: str = Field(default="", max_length=MAX_LEXICAL_RELATION_NOTE_CHARS)


class LexicalRelationGroup(StrictSchema):
    relation_type: Literal["synonym", "antonym", "derivative"]
    part_of_speech: str = Field(min_length=1, max_length=MAX_WORD_FAMILY_POS_CHARS)
    sense: str = Field(default="", max_length=MAX_LEXICAL_SENSE_CHARS)
    items: list[LexicalRelationItem] = Field(min_length=1, max_length=6)


class LexicalSectionStatus(StrictSchema):
    forms: Literal["source_validated", "verified_empty", "missing"]
    relations: Literal["source_validated", "verified_empty", "missing"]


class LexicalFactRecord(StrictSchema):
    """One complete, offline-validated lexical-fact record per headword."""

    schema_version: Literal[1]
    word: str = Field(min_length=1, max_length=100)
    level: Literal["CET4", "CET6"]
    source_kind: Literal["curated", "open"]
    source_meaning: str = Field(min_length=1, max_length=500)
    forms: list[LexicalParadigm] = Field(max_length=8)
    relations: list[LexicalRelationGroup] = Field(max_length=6)
    status: LexicalSectionStatus
    source: str = Field(min_length=1, max_length=120)
    content_hash: str = Field(min_length=64, max_length=64)


LexicalSourceUse = Literal[
    "forms",
    "part_of_speech",
    "english_gloss",
    "chinese_gloss",
    "frequency",
    "relation_candidates",
    "sense_alignment",
]


class LexicalSourceLicense(StrictSchema):
    """Reviewed redistribution terms for one exact lexical source release."""

    identifier: str = Field(min_length=1, max_length=80)
    reference: str = Field(min_length=1, max_length=500)
    redistribution: bool
    modification: bool
    commercial_use: bool
    notice_required: bool
    share_alike: bool


class LexicalSourceContract(StrictSchema):
    """Pinned source identity plus the fields it may contribute."""

    source_id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    name: str = Field(min_length=1, max_length=120)
    version: str = Field(min_length=1, max_length=120)
    filename: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    url: str = Field(min_length=1, max_length=500)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    review_status: Literal["approved", "candidate", "rejected"]
    license: LexicalSourceLicense
    approved_uses: list[LexicalSourceUse] = Field(max_length=7)
    attribution: list[str] = Field(max_length=6)
    notes: str = Field(default="", max_length=800)


class LexicalSourceManifest(StrictSchema):
    """Versioned allowlist consumed only by the offline lexical pipeline."""

    schema_version: Literal[1]
    policy_version: Literal["lexical-sources-v1"]
    reviewed_at: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    sources: list[LexicalSourceContract] = Field(min_length=1, max_length=10)


LexicalCandidateRole = Literal[
    "plural",
    "past",
    "past_participle",
    "present_participle",
    "third_person_singular",
    "comparative",
    "superlative",
]
LexicalCandidateOutcome = Literal[
    "source_addition",
    "source_agrees",
    "source_conflict",
]
LexicalCandidateConflictKind = Literal[
    "missing_current_form",
    "corroborated",
    "orthographic_variant_candidate",
    "possible_pos_or_sense",
    "deterministic_rule_candidate",
    "source_irregular_candidate",
]
LexicalCandidateFormValue = Annotated[
    str,
    Field(min_length=1, max_length=MAX_LEXICAL_FORM_CHARS),
]


class LexicalEvidence(StrictSchema):
    """A bounded, replayable pointer to one source field."""

    source_id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    source_version: str = Field(min_length=1, max_length=120)
    field: str = Field(min_length=1, max_length=40)
    locator: str = Field(min_length=1, max_length=MAX_LEXICAL_EVIDENCE_LOCATOR_CHARS)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class LexicalFormCandidate(StrictSchema):
    """One source-backed role comparison; never a promoted learner fact."""

    role: LexicalCandidateRole
    current_forms: list[LexicalCandidateFormValue] = Field(max_length=8)
    source_forms: list[LexicalCandidateFormValue] = Field(max_length=8)
    outcome: LexicalCandidateOutcome
    conflict_kind: LexicalCandidateConflictKind
    evidence: list[LexicalEvidence] = Field(min_length=1, max_length=2)
    note: str = Field(default="", max_length=MAX_LEXICAL_CANDIDATE_NOTE_CHARS)


class LexicalFactCandidateRecord(StrictSchema):
    """Complete candidate-only form evidence for one bundled headword."""

    schema_version: Literal[1]
    word: str = Field(min_length=1, max_length=100)
    level: Literal["CET4", "CET6"]
    source_kind: Literal["curated", "open"]
    source_meaning: str = Field(min_length=1, max_length=500)
    candidates: list[LexicalFormCandidate] = Field(max_length=8)
    candidate_status: Literal["candidate_only"]
    source_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source: str = Field(min_length=1, max_length=120)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class LexicalRelationCandidateItem(StrictSchema):
    """One WordNet/COW relation target retained for the review pilot."""

    word: str = Field(min_length=1, max_length=MAX_LEXICAL_RELATION_CHARS)
    meaning: str = Field(
        min_length=1,
        max_length=MAX_LEXICAL_RELATION_MEANING_CHARS,
    )
    english_definition: str = Field(max_length=MAX_LEXICAL_SENSE_CHARS)
    frequency: int = Field(ge=0, le=1_000_000)
    evidence: list[LexicalEvidence] = Field(min_length=2, max_length=3)
    note: str = Field(default="", max_length=MAX_LEXICAL_RELATION_NOTE_CHARS)


class LexicalRelationCandidateGroup(StrictSchema):
    """A sense-bound candidate relation group; it is not yet verified."""

    relation_type: Literal["synonym", "antonym"]
    synset_id: str = Field(min_length=1, max_length=120)
    ili: str = Field(min_length=1, max_length=120)
    part_of_speech: str = Field(min_length=1, max_length=MAX_WORD_FAMILY_POS_CHARS)
    sense: str = Field(min_length=1, max_length=MAX_LEXICAL_SENSE_CHARS)
    items: list[LexicalRelationCandidateItem] = Field(min_length=1, max_length=6)


class LexicalRelationCandidateRecord(StrictSchema):
    """Complete candidate-only relation evidence for one headword."""

    schema_version: Literal[1]
    word: str = Field(min_length=1, max_length=100)
    level: Literal["CET4", "CET6"]
    source_kind: Literal["curated", "open"]
    source_meaning: str = Field(min_length=1, max_length=500)
    groups: list[LexicalRelationCandidateGroup] = Field(max_length=4)
    selection_status: Literal[
        "selected_single_sense",
        "excluded_multiple_senses",
        "no_aligned_sense",
    ]
    candidate_status: Literal["candidate_only"]
    source_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source: str = Field(min_length=1, max_length=120)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
