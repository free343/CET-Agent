"""Build a conservative WordNet/COW relation-candidate pilot.

Chinese-aligned sense groups with frequency-bounded single-word ECDICT targets
are emitted.  Multiple aligned senses remain grouped and bounded instead of
being discarded wholesale.  The result is a review artifact and cannot be
imported as a verified lexical relation without a later human promotion gate.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from app.ai.schemas import (
    LexicalEvidence,
    LexicalRelationCandidateGroup,
    LexicalRelationCandidateItem,
    LexicalRelationCandidateRecord,
)
from app.db.seed import VocabularySeedRow
from app.domain.lexical_relation_quality import (
    has_learner_translation,
    learner_translation,
)
from app.domain.lexical_source_audit import chinese_sense_matches
from app.domain.lexical_source_readers import (
    ECDICTEntry,
    EnglishWordnetIndex,
    SenseData,
)

RELATION_CANDIDATE_SOURCE = "wordnet-cow-relation-candidates-v3"
MAX_RELATION_TARGET_FREQUENCY = 1_000_000
_HEADWORD_PATTERN = re.compile(r"[a-z]+(?:[-'][a-z]+)*")
_POS_LABELS = {
    "a": "adjective",
    "n": "noun",
    "r": "adverb",
    "v": "verb",
}
_POS_PATTERN = re.compile(r"(?<![A-Za-z])(adv|vt|vi|v|n|a)\.")


def build_relation_candidate_record(
    row: VocabularySeedRow,
    english: EnglishWordnetIndex,
    chinese_by_ili: dict[str, tuple[str, ...]],
    ecdict: dict[str, ECDICTEntry],
    *,
    oewn_version: str,
    oewn_sha256: str,
    cow_version: str,
    cow_sha256: str,
    ecdict_version: str,
    ecdict_sha256: str,
    manifest_sha256: str,
) -> LexicalRelationCandidateRecord:
    target_words = set(ecdict)
    aligned_groups = _aligned_groups(
        row,
        english,
        chinese_by_ili,
        ecdict,
        target_words,
        oewn_version=oewn_version,
        oewn_sha256=oewn_sha256,
        cow_version=cow_version,
        cow_sha256=cow_sha256,
        ecdict_version=ecdict_version,
        ecdict_sha256=ecdict_sha256,
    )
    flattened_groups = [
        group for sense_groups in aligned_groups for group in sense_groups
    ]
    selected_groups = _select_groups(flattened_groups)
    if not selected_groups:
        selection_status = "no_aligned_sense"
        groups: list[LexicalRelationCandidateGroup] = []
    elif len(aligned_groups) == 1:
        selection_status = "selected_single_sense"
        groups = selected_groups
    elif len(selected_groups) < len(flattened_groups):
        selection_status = "truncated_aligned_senses"
        groups = selected_groups
    else:
        selection_status = "selected_aligned_senses"
        groups = selected_groups

    record = LexicalRelationCandidateRecord(
        schema_version=1,
        word=row.word,
        level=row.level.value,
        source_kind="curated" if row.example else "open",
        source_meaning=row.meaning,
        groups=groups,
        selection_status=selection_status,
        candidate_status="candidate_only",
        source_manifest_sha256=manifest_sha256,
        source=RELATION_CANDIDATE_SOURCE,
        content_hash="0" * 64,
    )
    from app.ai.lexical_relation_candidate_validation import (
        lexical_relation_candidate_content_hash,
    )

    return record.model_copy(
        update={
            "content_hash": lexical_relation_candidate_content_hash(record),
        }
    )


def _aligned_groups(
    row: VocabularySeedRow,
    english: EnglishWordnetIndex,
    chinese_by_ili: dict[str, tuple[str, ...]],
    ecdict: dict[str, ECDICTEntry],
    target_words: set[str],
    *,
    oewn_version: str,
    oewn_sha256: str,
    cow_version: str,
    cow_sha256: str,
    ecdict_version: str,
    ecdict_sha256: str,
) -> list[list[LexicalRelationCandidateGroup]]:
    aligned: list[list[LexicalRelationCandidateGroup]] = []
    for sense in english.target_senses.get(row.word, []):
        synset = english.synsets.get(sense.synset_id)
        if synset is None:
            continue
        labels = chinese_by_ili.get(synset.ili, ())
        if not labels or not chinese_sense_matches(row.meaning, labels):
            continue
        sense_label = _compact_labels(labels)
        candidates = _candidate_words(
            row.word,
            synset.member_words,
            ecdict,
            target_words,
            sense.part_of_speech,
        )
        antonyms = _candidate_words(
            row.word,
            (
                english.sense_words[target]
                for target in sense.antonym_sense_ids
                if target in english.sense_words
            ),
            ecdict,
            target_words,
            sense.part_of_speech,
        )
        groups: list[LexicalRelationCandidateGroup] = []
        if candidates:
            groups.append(
                _build_group(
                    "synonym",
                    sense,
                    synset.ili,
                    sense_label,
                    candidates,
                    oewn_version=oewn_version,
                    oewn_sha256=oewn_sha256,
                    cow_version=cow_version,
                    cow_sha256=cow_sha256,
                    ecdict_version=ecdict_version,
                    ecdict_sha256=ecdict_sha256,
                    definition=synset.definition,
                )
            )
        if antonyms:
            groups.append(
                _build_group(
                    "antonym",
                    sense,
                    synset.ili,
                    sense_label,
                    antonyms,
                    oewn_version=oewn_version,
                    oewn_sha256=oewn_sha256,
                    cow_version=cow_version,
                    cow_sha256=cow_sha256,
                    ecdict_version=ecdict_version,
                    ecdict_sha256=ecdict_sha256,
                    definition=synset.definition,
                )
            )
        if groups:
            aligned.append(groups)
    return aligned


def _candidate_words(
    headword: str,
    values: Iterable[str],
    ecdict: dict[str, ECDICTEntry],
    target_words: set[str],
    part_of_speech: str,
) -> list[tuple[str, ECDICTEntry, str]]:
    unique: dict[str, tuple[ECDICTEntry, str]] = {}
    for value in values:
        word = value.strip().casefold()
        if word == headword or word not in target_words:
            continue
        if _HEADWORD_PATTERN.fullmatch(word) is None:
            continue
        entry = ecdict.get(word)
        if entry is None or entry.frequency <= 0:
            continue
        if entry.frequency > MAX_RELATION_TARGET_FREQUENCY:
            continue
        # Frequency is not a learner-suitability signal.  Reject rows whose
        # only Chinese gloss is specialist-tagged (for example ``homo`` has
        # only chemistry/medical senses in ECDICT).
        if not has_learner_translation(entry, part_of_speech=part_of_speech):
            continue
        if not _pos_compatible(entry, part_of_speech):
            continue
        unique[word] = (
            entry,
            learner_translation(entry.translation, part_of_speech=part_of_speech),
        )
    ordered = sorted(unique.items(), key=lambda item: (-item[1][0].frequency, item[0]))[
        :6
    ]
    return [(word, entry, meaning) for word, (entry, meaning) in ordered]


def _pos_compatible(entry: ECDICTEntry, part_of_speech: str) -> bool:
    text = f"{entry.part_of_speech} {entry.translation} {entry.definition}".replace(
        "\\n", " "
    )
    tokens = set(_POS_PATTERN.findall(text.casefold()))
    if not tokens:
        return True
    if part_of_speech == "a":
        return bool(tokens.intersection({"a", "adv"}))
    if part_of_speech == "r":
        return bool(tokens.intersection({"adv", "a"}))
    if part_of_speech == "n":
        return "n" in tokens
    if part_of_speech == "v":
        return bool(tokens.intersection({"v", "vt", "vi"}))
    return True


def _build_group(
    relation_type: str,
    sense: SenseData,
    ili: str,
    sense_label: str,
    candidates: list[tuple[str, ECDICTEntry, str]],
    *,
    oewn_version: str,
    oewn_sha256: str,
    cow_version: str,
    cow_sha256: str,
    ecdict_version: str,
    ecdict_sha256: str,
    definition: str,
) -> LexicalRelationCandidateGroup:
    part_of_speech = sense.part_of_speech
    return LexicalRelationCandidateGroup(
        relation_type=relation_type,
        synset_id=sense.synset_id,
        ili=ili,
        part_of_speech=_POS_LABELS.get(part_of_speech, part_of_speech),
        sense=sense_label,
        items=[
            LexicalRelationCandidateItem(
                word=word,
                meaning=meaning,
                english_definition=definition[:160],
                frequency=entry.frequency,
                evidence=[
                    LexicalEvidence(
                        source_id="oewn-2025",
                        source_version=oewn_version,
                        field="synset.members"
                        if relation_type == "synonym"
                        else "sense.antonym",
                        locator=(
                            f"english-wordnet-2025.xml.gz:synset={sense.synset_id}"
                            if relation_type == "synonym"
                            else (
                                "english-wordnet-2025.xml.gz:sense="
                                f"{sense.sense_id}:relation=antonym"
                            )
                        ),
                        source_sha256=oewn_sha256,
                    ),
                    LexicalEvidence(
                        source_id="omw-cmn-2",
                        source_version=cow_version,
                        field="synset.labels",
                        locator=f"omw-cmn.xml:ili={ili}",
                        source_sha256=cow_sha256,
                    ),
                    LexicalEvidence(
                        source_id="ecdict",
                        source_version=ecdict_version,
                        field="translation",
                        locator=f"ecdict.csv:word={word}:field=translation",
                        source_sha256=ecdict_sha256,
                    ),
                ],
                note="仅保留单词级、ECDICT 有普通中文释义、频率大于 0 且词性兼容的候选；关系可能超出 CET 词库，需人工审核。",
            )
            for word, entry, meaning in candidates
        ],
    )


def _compact_labels(labels: tuple[str, ...]) -> str:
    return "；".join(label.strip() for label in labels[:3] if label.strip())[:160]


def _select_groups(
    groups: list[LexicalRelationCandidateGroup],
) -> list[LexicalRelationCandidateGroup]:
    """Keep the strongest four groups while preserving both relation types."""
    if len(groups) <= 4:
        return groups
    unique: dict[tuple[str, str], LexicalRelationCandidateGroup] = {}
    for group in groups:
        unique.setdefault((group.relation_type, group.synset_id), group)
    ordered = sorted(
        unique.values(),
        key=lambda group: (
            -max(item.frequency for item in group.items),
            0 if group.relation_type == "synonym" else 1,
            group.synset_id,
        ),
    )
    selected: list[LexicalRelationCandidateGroup] = []
    for relation_type in ("synonym", "antonym"):
        first = next(
            (group for group in ordered if group.relation_type == relation_type),
            None,
        )
        if first is not None:
            selected.append(first)
    for group in ordered:
        if group not in selected:
            selected.append(group)
        if len(selected) >= 4:
            break
    return selected[:4]
