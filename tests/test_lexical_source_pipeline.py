"""Source-contract and parser tests for lexical-card phase 2."""

from __future__ import annotations

import gzip
import io
import json
import tarfile
from io import StringIO
from pathlib import Path

import pytest

from app.ai.lexical_source_validation import (
    LexicalSourceDataError,
    load_lexical_source_manifest,
    verify_lexical_source_file,
)
from app.domain.lexical_source_audit import chinese_sense_matches
from app.domain.lexical_source_readers import (
    parse_chinese_wordnet,
    parse_ecdict,
    parse_english_wordnet,
    parse_exchange,
)


def test_parse_ecdict_counts_each_exchange_code_once_per_headword() -> None:
    source = StringIO(
        "word,pos,definition,translation,exchange,frq\n"
        "go,v,move,去,p:went/d:gone/i:going/3:goes,35\n"
        "child,n,young person,孩子,s:children,120\n"
    )

    entries, counts = parse_ecdict(source, {"go", "child"})

    assert set(entries) == {"go", "child"}
    assert counts == {"3": 1, "d": 1, "i": 1, "p": 1, "s": 1}
    assert entries["go"].frequency == 35


def test_exchange_parser_preserves_repeated_variants_without_duplicates() -> None:
    assert parse_exchange("p:learned/p:learnt/p:learned/d:learned") == {
        "p": ("learned", "learnt"),
        "d": ("learned",),
    }


def test_chinese_alignment_requires_real_segment_overlap() -> None:
    assert chinese_sense_matches("adj. 主要的；最重要的", ("主要的", "首要的"))
    assert not chinese_sense_matches("n. 苹果；苹果树", ("公司", "企业"))
    assert not chinese_sense_matches("adj. 广大的", ("大",))


def test_bundled_source_manifest_is_approved_and_unique() -> None:
    manifest = load_lexical_source_manifest(Path("data/lexical_source_manifest.json"))

    assert [source.source_id for source in manifest.sources] == [
        "ecdict",
        "oewn-2025",
        "omw-cmn-2",
    ]
    assert all(source.review_status == "approved" for source in manifest.sources)


def test_source_manifest_rejects_approved_source_without_reuse_rights(
    tmp_path: Path,
) -> None:
    payload = json.loads(Path("data/lexical_source_manifest.json").read_text("utf-8"))
    payload["sources"][0]["license"]["redistribution"] = False
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(LexicalSourceDataError, match="lacks required reuse rights"):
        load_lexical_source_manifest(path)


def test_source_file_hash_mismatch_is_rejected(tmp_path: Path) -> None:
    manifest = load_lexical_source_manifest(Path("data/lexical_source_manifest.json"))
    path = tmp_path / manifest.sources[0].filename
    path.write_bytes(b"not the pinned dictionary")

    with pytest.raises(LexicalSourceDataError, match="SHA-256 mismatch"):
        verify_lexical_source_file(manifest.sources[0], path)


def test_wordnet_readers_preserve_synset_antonym_and_shared_ili(
    tmp_path: Path,
) -> None:
    english_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<LexicalResource><Lexicon id="oewn" version="2025"
license="https://creativecommons.org/licenses/by/4.0">
<LexicalEntry id="main-a"><Lemma writtenForm="main" partOfSpeech="a"/>
<Sense id="main-s" synset="syn-main"><SenseRelation relType="antonym"
target="secondary-s"/></Sense></LexicalEntry>
<LexicalEntry id="primary-a"><Lemma writtenForm="primary" partOfSpeech="a"/>
<Sense id="primary-s" synset="syn-main"/></LexicalEntry>
<LexicalEntry id="secondary-a"><Lemma writtenForm="secondary" partOfSpeech="a"/>
<Sense id="secondary-s" synset="syn-secondary"/></LexicalEntry>
<Synset id="syn-main" ili="i-main" members="main-a primary-a">
<Definition>most important</Definition></Synset>
<Synset id="syn-secondary" ili="i-secondary" members="secondary-a"/>
</Lexicon></LexicalResource>"""
    english_path = tmp_path / "english.xml.gz"
    with gzip.open(english_path, "wb") as target:
        target.write(english_xml)

    chinese_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<LexicalResource><Lexicon id="omw-cmn" version="2.0">
<LexicalEntry id="cmn-main-a"><Lemma writtenForm="\xe4\xb8\xbb\xe8\xa6\x81\xe7\x9a\x84" partOfSpeech="a"/>
<Sense id="cmn-main-s" synset="cmn-main"/></LexicalEntry>
<Synset id="cmn-main" ili="i-main" members="cmn-main-s"/>
</Lexicon></LexicalResource>"""
    chinese_path = tmp_path / "chinese.tar.xz"
    with tarfile.open(chinese_path, "w:xz") as archive:
        _add_tar_bytes(
            archive,
            "omw-cmn/LICENSE",
            b"Permission to use, copy, modify and distribute this database",
        )
        _add_tar_bytes(archive, "omw-cmn/omw-cmn.xml", chinese_xml)

    english = parse_english_wordnet(english_path, {"main"})
    chinese = parse_chinese_wordnet(chinese_path)

    sense = english.target_senses["main"][0]
    assert sense.antonym_sense_ids == ("secondary-s",)
    assert english.synsets["syn-main"].member_words == ("main", "primary")
    assert english.sense_words["secondary-s"] == "secondary"
    assert chinese["i-main"] == ("主要的",)


def _add_tar_bytes(archive: tarfile.TarFile, name: str, payload: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(payload)
    archive.addfile(info, io.BytesIO(payload))
