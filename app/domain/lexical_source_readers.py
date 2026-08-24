"""Deterministic readers for pinned lexical dictionary releases."""

from __future__ import annotations

import csv
import gzip
import tarfile
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import IO, TextIO


@dataclass(frozen=True, slots=True)
class ECDICTEntry:
    part_of_speech: str
    translation: str
    definition: str
    exchange: dict[str, tuple[str, ...]]
    frequency: int = 0


@dataclass(frozen=True, slots=True)
class SenseData:
    synset_id: str
    part_of_speech: str
    antonym_sense_ids: tuple[str, ...]
    sense_id: str = ""


@dataclass(frozen=True, slots=True)
class SynsetData:
    ili: str
    definition: str
    member_words: tuple[str, ...]


@dataclass(slots=True)
class EnglishWordnetIndex:
    target_senses: dict[str, list[SenseData]]
    sense_words: dict[str, str]
    sense_synsets: dict[str, str]
    synsets: dict[str, SynsetData]


def parse_exchange(raw: str) -> dict[str, tuple[str, ...]]:
    values: dict[str, list[str]] = defaultdict(list)
    for item in raw.split("/"):
        code, separator, value = item.partition(":")
        normalized = value.strip().casefold()
        if not separator or not code.strip() or not normalized:
            continue
        bucket = values[code.strip()]
        if normalized not in bucket:
            bucket.append(normalized)
    return {code: tuple(items) for code, items in values.items()}


def parse_ecdict(
    source: TextIO, target_words: set[str]
) -> tuple[dict[str, ECDICTEntry], Counter[str]]:
    reader = csv.DictReader(source)
    required = {"word", "pos", "definition", "translation", "exchange"}
    missing = required - set(reader.fieldnames or ())
    if missing:
        raise ValueError(f"ECDICT source is missing columns: {sorted(missing)}")
    entries: dict[str, ECDICTEntry] = {}
    codes: Counter[str] = Counter()
    for row in reader:
        word = (row.get("word") or "").strip().casefold()
        if word not in target_words:
            continue
        if word in entries:
            raise ValueError(f"ECDICT contains a duplicate target headword: {word}")
        exchange = parse_exchange(row.get("exchange") or "")
        codes.update(exchange.keys())
        entries[word] = ECDICTEntry(
            part_of_speech=(row.get("pos") or "").strip(),
            translation=(row.get("translation") or "").strip(),
            definition=(row.get("definition") or "").strip(),
            exchange=exchange,
            frequency=_parse_frequency(row.get("frq") or ""),
        )
    return entries, codes


def parse_english_wordnet(path: Path, target_words: set[str]) -> EnglishWordnetIndex:
    member_words: dict[str, str] = {}
    sense_words: dict[str, str] = {}
    sense_synsets: dict[str, str] = {}
    target_senses: dict[str, list[SenseData]] = defaultdict(list)
    synsets: dict[str, SynsetData] = {}
    needed_synsets: set[str] = set()
    lexicon_checked = False
    synsets_started = False

    with gzip.open(path, "rb") as source:
        for event, element in ET.iterparse(source, events=("start", "end")):
            tag = _local_name(element.tag)
            if event == "start" and tag == "Lexicon":
                if element.get("version") != "2025":
                    raise ValueError("Open English WordNet version is not 2025")
                if "creativecommons.org/licenses/by/4.0" not in (
                    element.get("license") or ""
                ):
                    raise ValueError("Open English WordNet license marker is missing")
                lexicon_checked = True
                continue
            if event != "end":
                continue
            if tag == "LexicalEntry":
                if synsets_started:
                    raise ValueError(
                        "WordNet lexical entries follow synsets unexpectedly"
                    )
                lemma = element.find("Lemma")
                entry_id = element.get("id") or ""
                word = (lemma.get("writtenForm") if lemma is not None else "") or ""
                word = word.strip().casefold()
                part_of_speech = (
                    lemma.get("partOfSpeech") if lemma is not None else ""
                ) or ""
                member_words[entry_id] = word
                for sense in element.findall("Sense"):
                    sense_id = sense.get("id") or ""
                    synset_id = sense.get("synset") or ""
                    if not sense_id or not synset_id:
                        continue
                    member_words[sense_id] = word
                    sense_words[sense_id] = word
                    sense_synsets[sense_id] = synset_id
                    if word in target_words:
                        antonyms = tuple(
                            relation.get("target") or ""
                            for relation in sense.findall("SenseRelation")
                            if relation.get("relType") == "antonym"
                            and relation.get("target")
                        )
                        target_senses[word].append(
                            SenseData(synset_id, part_of_speech, antonyms, sense_id)
                        )
                        needed_synsets.add(synset_id)
                element.clear()
            elif tag == "Synset":
                if not synsets_started:
                    for senses in target_senses.values():
                        for sense in senses:
                            for antonym_id in sense.antonym_sense_ids:
                                target = sense_synsets.get(antonym_id)
                                if target:
                                    needed_synsets.add(target)
                    synsets_started = True
                synset_id = element.get("id") or ""
                if synset_id in needed_synsets:
                    definition = element.findtext("Definition", default="").strip()
                    members = tuple(
                        member_words.get(member, "")
                        for member in (element.get("members") or "").split()
                    )
                    synsets[synset_id] = SynsetData(
                        ili=element.get("ili") or "",
                        definition=definition,
                        member_words=tuple(word for word in members if word),
                    )
                element.clear()
    if not lexicon_checked:
        raise ValueError("Open English WordNet Lexicon metadata is missing")
    return EnglishWordnetIndex(
        target_senses=dict(target_senses),
        sense_words=sense_words,
        sense_synsets=sense_synsets,
        synsets=synsets,
    )


def parse_chinese_wordnet(archive_path: Path) -> dict[str, tuple[str, ...]]:
    with tarfile.open(archive_path, mode="r:xz") as archive:
        license_member = archive.getmember("omw-cmn/LICENSE")
        license_stream = archive.extractfile(license_member)
        if license_stream is None:
            raise ValueError("Chinese Open Wordnet license is unavailable")
        with license_stream:
            license_text = license_stream.read().decode("utf-8")
        required_grant = "Permission to use, copy, modify and distribute"
        if required_grant not in license_text:
            raise ValueError("Chinese Open Wordnet license grant is unexpected")
        xml_member = archive.getmember("omw-cmn/omw-cmn.xml")
        xml_stream = archive.extractfile(xml_member)
        if xml_stream is None:
            raise ValueError("Chinese Open Wordnet XML is unavailable")
        with xml_stream:
            return _parse_chinese_wordnet_xml(xml_stream)


def _parse_chinese_wordnet_xml(source: IO[bytes]) -> dict[str, tuple[str, ...]]:
    member_words: dict[str, str] = {}
    labels_by_ili: dict[str, tuple[str, ...]] = {}
    lexicon_checked = False
    for event, element in ET.iterparse(source, events=("start", "end")):
        tag = _local_name(element.tag)
        if event == "start" and tag == "Lexicon":
            if element.get("id") != "omw-cmn" or element.get("version") != "2.0":
                raise ValueError("Chinese Open Wordnet identity is unexpected")
            lexicon_checked = True
            continue
        if event != "end":
            continue
        if tag == "LexicalEntry":
            lemma = element.find("Lemma")
            word = (lemma.get("writtenForm") if lemma is not None else "") or ""
            word = word.strip()
            member_words[element.get("id") or ""] = word
            for sense in element.findall("Sense"):
                member_words[sense.get("id") or ""] = word
            element.clear()
        elif tag == "Synset":
            ili = element.get("ili") or ""
            labels: list[str] = []
            for member in (element.get("members") or "").split():
                label = member_words.get(member, "")
                if label and label not in labels:
                    labels.append(label)
            if ili and labels:
                labels_by_ili[ili] = tuple(labels)
            element.clear()
    if not lexicon_checked:
        raise ValueError("Chinese Open Wordnet Lexicon metadata is missing")
    return labels_by_ili


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_frequency(raw: str) -> int:
    try:
        value = int(raw.strip() or "0")
    except ValueError:
        return 0
    return max(0, min(value, 1_000_000))
