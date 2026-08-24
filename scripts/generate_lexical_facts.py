"""Build the deterministic lexical-fact artifact from bundled vocabulary.

The generator is intentionally offline.  Regular paradigms are emitted only
for an audited, bounded rule set; irregular and sense-sensitive facts live in
the explicit exception tables below.  It never asks an LLM to invent a fact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ai.lexical_fact_validation import lexical_fact_content_hash
from app.ai.schemas import (
    DegreeParadigm,
    LexicalFactRecord,
    LexicalRelationGroup,
    LexicalRelationItem,
    LexicalSectionStatus,
    LexicalSurfaceForm,
    NounParadigm,
    NumeralParadigm,
    PronounParadigm,
    VerbParadigm,
)
from app.db.seed import VocabularySeedRow, load_vocabulary_rows

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "word_lexical_facts.jsonl"
DEFAULT_PROVENANCE = PROJECT_ROOT / "data" / "word_lexical_facts.provenance.json"

_CONSONANTS = set("bcdfghjklmnpqrstvwxyz")
_UNCOUNTABLE = {
    "advice",
    "equipment",
    "furniture",
    "information",
    "knowledge",
    "luggage",
    "news",
    "progress",
    "research",
    "traffic",
    "work",
}

_IRREGULAR_NOUNS: dict[str, tuple[str, str]] = {
    "child": ("children", "拼写变化"),
    "person": ("people", "拼写变化"),
    "man": ("men", "拼写变化"),
    "woman": ("women", "拼写变化"),
    "mouse": ("mice", "拼写变化"),
    "tooth": ("teeth", "拼写变化"),
    "foot": ("feet", "拼写变化"),
    "goose": ("geese", "拼写变化"),
    "sheep": ("sheep", "单复数同形"),
    "deer": ("deer", "单复数同形"),
    "fish": ("fish", "通常单复数同形"),
}

_IRREGULAR_VERBS: dict[str, tuple[str, str, str, str]] = {
    "be": ("is", "was/were", "been", "being"),
    "go": ("goes", "went", "gone", "going"),
    "read": ("reads", "read", "read", "reading"),
    "have": ("has", "had", "had", "having"),
    "do": ("does", "did", "done", "doing"),
    "make": ("makes", "made", "made", "making"),
    "take": ("takes", "took", "taken", "taking"),
    "see": ("sees", "saw", "seen", "seeing"),
    "give": ("gives", "gave", "given", "giving"),
    "get": ("gets", "got", "got/gotten", "getting"),
    "know": ("knows", "knew", "known", "knowing"),
    "think": ("thinks", "thought", "thought", "thinking"),
    "say": ("says", "said", "said", "saying"),
    "tell": ("tells", "told", "told", "telling"),
    "find": ("finds", "found", "found", "finding"),
    "leave": ("leaves", "left", "left", "leaving"),
    "feel": ("feels", "felt", "felt", "feeling"),
    "keep": ("keeps", "kept", "kept", "keeping"),
    "begin": ("begins", "began", "begun", "beginning"),
    "break": ("breaks", "broke", "broken", "breaking"),
    "bring": ("brings", "brought", "brought", "bringing"),
    "build": ("builds", "built", "built", "building"),
    "buy": ("buys", "bought", "bought", "buying"),
    "catch": ("catches", "caught", "caught", "catching"),
    "choose": ("chooses", "chose", "chosen", "choosing"),
    "come": ("comes", "came", "come", "coming"),
    "cut": ("cuts", "cut", "cut", "cutting"),
    "draw": ("draws", "drew", "drawn", "drawing"),
    "drink": ("drinks", "drank", "drunk", "drinking"),
    "drive": ("drives", "drove", "driven", "driving"),
    "eat": ("eats", "ate", "eaten", "eating"),
    "fall": ("falls", "fell", "fallen", "falling"),
    "fly": ("flies", "flew", "flown", "flying"),
    "forget": ("forgets", "forgot", "forgotten", "forgetting"),
    "freeze": ("freezes", "froze", "frozen", "freezing"),
    "grow": ("grows", "grew", "grown", "growing"),
    "hear": ("hears", "heard", "heard", "hearing"),
    "hold": ("holds", "held", "held", "holding"),
    "hurt": ("hurts", "hurt", "hurt", "hurting"),
    "lead": ("leads", "led", "led", "leading"),
    "lose": ("loses", "lost", "lost", "losing"),
    "meet": ("meets", "met", "met", "meeting"),
    "pay": ("pays", "paid", "paid", "paying"),
    "put": ("puts", "put", "put", "putting"),
    "rise": ("rises", "rose", "risen", "rising"),
    "run": ("runs", "ran", "run", "running"),
    "sell": ("sells", "sold", "sold", "selling"),
    "send": ("sends", "sent", "sent", "sending"),
    "set": ("sets", "set", "set", "setting"),
    "sing": ("sings", "sang", "sung", "singing"),
    "sit": ("sits", "sat", "sat", "sitting"),
    "sleep": ("sleeps", "slept", "slept", "sleeping"),
    "speak": ("speaks", "spoke", "spoken", "speaking"),
    "spend": ("spends", "spent", "spent", "spending"),
    "stand": ("stands", "stood", "stood", "standing"),
    "swim": ("swims", "swam", "swum", "swimming"),
    "teach": ("teaches", "taught", "taught", "teaching"),
    "throw": ("throws", "threw", "thrown", "throwing"),
    "understand": ("understands", "understood", "understood", "understanding"),
    "wear": ("wears", "wore", "worn", "wearing"),
    "win": ("wins", "won", "won", "winning"),
    "write": ("writes", "wrote", "written", "writing"),
}

_DEGREES: dict[str, tuple[str, str, str, str, str]] = {
    "good": ("good", "better", "best", "adjective", "不规则变化"),
    "bad": ("bad", "worse", "worst", "adjective", "不规则变化"),
    "far": (
        "far",
        "farther/further",
        "farthest/furthest",
        "adjective",
        "距离与抽象意义有不同偏好",
    ),
    "little": (
        "little",
        "less",
        "least",
        "adjective",
        "数量；small-size little 另有规则变化",
    ),
    "less": ("little", "less", "least", "adjective", "数量；原级为 little"),
    "many": ("many", "more", "most", "adjective", "可数名词数量"),
    "much": ("much", "more", "most", "adjective", "不可数名词数量"),
    "few": (
        "few",
        "fewer",
        "fewest",
        "adjective",
        "可数名词数量；不要与 little/less 混淆",
    ),
}

_RELATIONS: dict[str, list[LexicalRelationGroup]] = {
    "less": [
        LexicalRelationGroup(
            relation_type="antonym",
            part_of_speech="adjective/adverb",
            sense="数量或程度",
            items=[LexicalRelationItem(word="more", meaning="更多；更大程度")],
        )
    ],
    "main": [
        LexicalRelationGroup(
            relation_type="synonym",
            part_of_speech="adjective",
            sense="主要的",
            items=[LexicalRelationItem(word="primary", meaning="主要的")],
        )
    ],
    "adapt": [
        LexicalRelationGroup(
            relation_type="synonym",
            part_of_speech="verb",
            sense="适应",
            items=[LexicalRelationItem(word="adjust", meaning="调整；适应")],
        )
    ],
}

_NUMERALS: dict[str, tuple[str, str]] = {
    "one": ("one", "first"),
    "two": ("two", "second"),
    "three": ("three", "third"),
    "four": ("four", "fourth"),
    "five": ("five", "fifth"),
    "six": ("six", "sixth"),
    "seven": ("seven", "seventh"),
    "eight": ("eight", "eighth"),
    "nine": ("nine", "ninth"),
    "ten": ("ten", "tenth"),
}

_PRONOUNS: dict[str, tuple[str, str, str, str]] = {
    "anyone": ("anyone", "anyone", "anyone's", "themselves"),
    "everyone": ("everyone", "everyone", "everyone's", "themselves"),
    "someone": ("someone", "someone", "someone's", "themselves"),
    "nobody": ("nobody", "nobody", "nobody's", "themselves"),
}


def _surface(
    role: str, value: str, *, note: str = "", sense: str = ""
) -> LexicalSurfaceForm:
    return LexicalSurfaceForm(role=role, value=value, note=note, sense=sense)


def _pos_flags(meaning: str) -> tuple[bool, bool, bool, bool]:
    lowered = meaning.casefold()
    return (
        bool(re.search(r"(?:^|[；;，, ])n\.", lowered)),
        bool(re.search(r"(?:^|[；;，, ])(?:v|vt|vi)\.", lowered)),
        bool(re.search(r"(?:^|[；;，, ])a\.", lowered)),
        bool(re.search(r"(?:^|[；;，, ])adv\.", lowered)),
    )


def _regular_plural(word: str) -> str | None:
    if not re.fullmatch(r"[a-z]+", word) or word in _UNCOUNTABLE:
        return None
    if word.endswith(("s", "x", "z", "ch", "sh")):
        return word + "es"
    if len(word) > 1 and word.endswith("y") and word[-2] not in "aeiou":
        return word[:-1] + "ies"
    if word.endswith("fe"):
        return word[:-2] + "ves"
    if word.endswith("f") and word not in {"roof", "chief", "belief"}:
        return word[:-1] + "ves"
    return word + "s"


def _regular_verb_forms(word: str) -> tuple[str, str, str, str]:
    if word.endswith("y") and len(word) > 1 and word[-2] not in "aeiou":
        third = word[:-1] + "ies"
        past = word[:-1] + "ied"
    elif word.endswith(("s", "x", "z", "ch", "sh", "o")):
        third = word + "es"
        past = word + "ed"
    else:
        third = word + "s"
        past = word + ("d" if word.endswith("e") else "ed")
    if word.endswith("e"):
        ing = word[:-1] + "ing"
    elif (
        len(word) >= 3
        and word[-1] in _CONSONANTS
        and word[-2] in "aeiou"
        and word[-3] in _CONSONANTS
    ):
        ing = word + word[-1] + "ing"
    else:
        ing = word + "ing"
    return third, past, past, ing


def build_forms(row: VocabularySeedRow) -> list[object]:
    word = row.word
    noun, verb, _adjective, _adverb = _pos_flags(row.meaning)
    forms: list[object] = []
    if word in _IRREGULAR_NOUNS:
        plural, note = _IRREGULAR_NOUNS[word]
        forms.append(
            NounParadigm(
                paradigm_type="noun",
                countability="invariant" if plural == word else "countable",
                forms=[
                    _surface("singular", word),
                    _surface("plural", plural, note=note),
                ],
            )
        )
    elif noun and word not in _UNCOUNTABLE and not word.endswith("s"):
        regular_plural = _regular_plural(word)
        if regular_plural:
            forms.append(
                NounParadigm(
                    paradigm_type="noun",
                    countability="countable",
                    forms=[
                        _surface("singular", word),
                        _surface("plural", regular_plural, note="按常规拼写规则"),
                    ],
                )
            )
    elif noun and word in _UNCOUNTABLE:
        forms.append(
            NounParadigm(
                paradigm_type="noun",
                countability="uncountable",
                forms=[
                    _surface(
                        "singular", word, note="通常不可数；不要直接加 -s 表示该义"
                    ),
                ],
            )
        )
    if verb:
        values = _IRREGULAR_VERBS.get(word) or _regular_verb_forms(word)
        notes = "拼写不变但读音变化" if word == "read" else ""
        forms.append(
            VerbParadigm(
                paradigm_type="verb",
                forms=[
                    _surface("base", word),
                    _surface("third_person_singular", values[0]),
                    _surface("past", values[1], note=notes),
                    _surface("past_participle", values[2], note=notes),
                    _surface("present_participle", values[3]),
                ],
            )
        )
    if word in _DEGREES:
        positive, comparative, superlative, pos, note = _DEGREES[word]
        forms.append(
            DegreeParadigm(
                paradigm_type="degree",
                part_of_speech=pos,
                gradability="contextual",
                forms=[
                    _surface("positive", positive, note=note),
                    _surface("comparative", comparative, note=note),
                    _surface("superlative", superlative, note=note),
                ],
            )
        )
    if word in _NUMERALS:
        cardinal, ordinal = _NUMERALS[word]
        forms.append(
            NumeralParadigm(
                paradigm_type="numeral",
                forms=[_surface("cardinal", cardinal), _surface("ordinal", ordinal)],
            )
        )
    if word in _PRONOUNS:
        subject, obj, possessive, reflexive = _PRONOUNS[word]
        forms.append(
            PronounParadigm(
                paradigm_type="pronoun",
                forms=[
                    _surface("subject", subject),
                    _surface("object", obj),
                    _surface("possessive", possessive),
                    _surface("reflexive", reflexive),
                ],
            )
        )
    return forms


def build_record(row: VocabularySeedRow) -> LexicalFactRecord:
    forms = build_forms(row)
    relations = _RELATIONS.get(row.word, [])
    record = LexicalFactRecord(
        schema_version=1,
        word=row.word,
        level=row.level.value,
        source_kind="curated" if row.example else "open",
        source_meaning=row.meaning,
        forms=forms,
        relations=relations,
        status=LexicalSectionStatus(
            forms="source_validated" if forms else "missing",
            relations="source_validated" if relations else "missing",
        ),
        source="audited-deterministic-rules-v1",
        content_hash="0" * 64,
    )
    return record.model_copy(update={"content_hash": lexical_fact_content_hash(record)})


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def generate(
    output: Path = DEFAULT_OUTPUT, provenance: Path = DEFAULT_PROVENANCE
) -> dict[str, object]:
    sources: list[VocabularySeedRow] = []
    source_files = (
        PROJECT_ROOT / "data" / "sample_words.csv",
        PROJECT_ROOT / "data" / "cet_vocabulary_open.csv",
    )
    for path in source_files:
        sources.extend(load_vocabulary_rows(path))
    records = [build_record(row) for row in sources]
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as target:
        for record in records:
            target.write(record.model_dump_json(by_alias=True) + "\n")
    counts = {
        "total": len(records),
        "forms_present": sum(bool(record.forms) for record in records),
        "relations_present": sum(bool(record.relations) for record in records),
        "source_validated_forms": sum(
            record.status.forms == "source_validated" for record in records
        ),
        "missing_forms": sum(record.status.forms == "missing" for record in records),
    }
    payload: dict[str, object] = {
        "schema_version": 1,
        "artifact": {
            "file": output.name,
            "sha256": _digest(output),
            "rows": len(records),
            "counts": counts,
        },
        "sources": [
            {
                "file": path.name,
                "sha256": _digest(path),
                "license": (
                    "project-curated"
                    if path.name == "sample_words.csv"
                    else "CC-BY-SA-3.0; source provenance in "
                    "cet_vocabulary_open.provenance.json"
                ),
            }
            for path in source_files
        ],
        "transformation": "audited-deterministic-rules-v1; no LLM calls; unresolved facts remain missing",
    }
    provenance.parent.mkdir(parents=True, exist_ok=True)
    provenance.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--provenance", type=Path, default=DEFAULT_PROVENANCE)
    args = parser.parse_args()
    payload = generate(args.output, args.provenance)
    print(json.dumps(payload["artifact"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
