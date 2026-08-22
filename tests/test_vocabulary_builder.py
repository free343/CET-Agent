from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from collections import Counter

from app.config import PROJECT_ROOT
from app.db.seed import load_vocabulary_rows
from scripts.build_open_vocabulary import (
    DictionaryEntry,
    build_rows,
    parse_ecdict_csv,
    parse_freedict_tei,
)


def test_open_source_parsers_and_release_schedule_are_deterministic() -> None:
    tei = """<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body>
  <entry><form><orth>Ability</orth><pron>əˈbɪləti</pron></form>
    <sense><cit type="trans"><quote>能力</quote></cit></sense></entry>
  <entry><form><orth>Adept</orth><pron>əˈdɛpt</pron></form>
    <sense><cit type="trans"><quote>熟练的</quote></cit></sense></entry>
  <entry><form><orth>Able</orth><pron>ˈeɪbəl</pron></form>
    <sense><cit type="trans"><quote>能够的</quote></cit></sense></entry>
</body></text></TEI>""".encode()
    ecdict = io.StringIO(
        "word,phonetic,translation,tag,frq,bnc\n"
        "ability,ә'biliti,n. 能力,cet4,10,20\n"
        "able,'eibl,a. 能够的,cet4,20,30\n"
        "adept,ә'dept,a. 熟练的,cet6,30,40\n"
        "ignored,,忽略,toefl,1,1\n"
    )

    dictionary = parse_freedict_tei(io.BytesIO(tei))
    headwords = parse_ecdict_csv(ecdict)
    rows = build_rows(headwords, dictionary, daily_new_words=1)

    assert dictionary["ability"].translations == ("能力",)
    assert rows == [
        {
            "word": "ability",
            "phonetic": "/ə'biliti/",
            "meaning": "n. 能力",
            "example": "",
            "level": "CET4",
            "frequency": 9_990,
            "initial_delay_days": 0,
        },
        {
            "word": "able",
            "phonetic": "/'eibl/",
            "meaning": "a. 能够的",
            "example": "",
            "level": "CET4",
            "frequency": 9_980,
            "initial_delay_days": 1,
        },
        {
            "word": "adept",
            "phonetic": "/ə'dept/",
            "meaning": "a. 熟练的",
            "example": "",
            "level": "CET6",
            "frequency": 9_970,
            "initial_delay_days": 0,
        },
    ]


def test_committed_open_vocabulary_matches_provenance_and_policy() -> None:
    artifact_path = PROJECT_ROOT / "data" / "cet_vocabulary_open.csv"
    provenance_path = PROJECT_ROOT / "data" / "cet_vocabulary_open.provenance.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    artifact = provenance["artifact"]
    digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    imported = load_vocabulary_rows(artifact_path)

    with artifact_path.open("r", encoding="utf-8", newline="") as source:
        raw_rows = list(csv.DictReader(source))
    with (PROJECT_ROOT / "data" / "sample_words.csv").open(
        "r", encoding="utf-8", newline=""
    ) as source:
        curated_words = {row["word"].lower() for row in csv.DictReader(source)}

    words = [row.word for row in imported]
    level_counts = Counter(row.level.value for row in imported)
    delay_counts = Counter(
        (row.level.value, row.initial_delay_days) for row in imported
    )

    assert digest == artifact["sha256"]
    assert len(imported) == artifact["rows"] == 4_598
    assert dict(level_counts) == artifact["level_counts"]
    assert len(words) == len(set(words))
    assert not curated_words.intersection(words)
    assert all(row.phonetic for row in imported)
    assert all(re.search(r"[\u3400-\u9fff]", row.meaning) for row in imported)
    assert all("\ufffd" not in row.phonetic + row.meaning for row in imported)
    assert all(re.search(r"<[^>]+>", row.meaning) is None for row in imported)
    assert all(
        count <= artifact["daily_new_words_per_level"]
        for count in delay_counts.values()
    )
    assert len(raw_rows) == len(imported)


def test_rows_require_validation_from_both_sources() -> None:
    rows = build_rows(
        {
            "known": parse_ecdict_csv(
                io.StringIO(
                    "word,phonetic,translation,tag,frq,bnc\n"
                    "known,noun,已知,cet4,1,1\n"
                )
            )["known"]
        },
        {"known": DictionaryEntry(pronunciations=(), translations=("已知",))},
    )

    assert rows == []
