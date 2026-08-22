"""Build the redistributable CET vocabulary artifact from pinned open sources."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import tarfile
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import IO, TextIO

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "cet_vocabulary_open.csv"
CURATED_SOURCE = PROJECT_ROOT / "data" / "sample_words.csv"

ECDICT_REVISION = "bc015ed2e24a7abef49fc6dbbb7fe32c1dadaf8b"
ECDICT_URL = (
    "https://raw.githubusercontent.com/skywind3000/ECDICT/"
    f"{ECDICT_REVISION}/ecdict.csv"
)
ECDICT_SHA256 = "1a6947e04785db63613a92e14903cdae7954f7e84860b10e68e5c7cbb3f9c3cf"

FREEDICT_VERSION = "2025.11.23"
FREEDICT_URL = (
    "https://download.freedict.org/dictionaries/eng-zho/2025.11.23/"
    "freedict-eng-zho-2025.11.23.src.tar.xz"
)
FREEDICT_SHA512 = (
    "25aed0f1d7de68919aa9da1ba92d67f566ae4ea81660f42071c81fc21e56d4b2"
    "10d61df379315678648c45ca7e52c4a0ba2eec009fbaab7c72e7472489e1fc4c"
)
FREEDICT_TEI_MEMBER = "eng-zho/eng-zho.tei"

_TEI = "{http://www.tei-c.org/ns/1.0}"
_HEADWORD_PATTERN = re.compile(r"[a-z]+(?:[-'][a-z]+)*")
_CHINESE_PATTERN = re.compile(r"[\u3400-\u9fff]")
_OUTPUT_FIELDS = (
    "word",
    "phonetic",
    "meaning",
    "example",
    "level",
    "frequency",
    "initial_delay_days",
)


@dataclass(frozen=True, slots=True)
class DictionaryEntry:
    pronunciations: tuple[str, ...]
    translations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TaggedHeadword:
    word: str
    level: str
    frequency: int
    phonetic: str
    translation: str


def parse_freedict_tei(source: IO[bytes]) -> dict[str, DictionaryEntry]:
    merged: dict[str, dict[str, list[str]]] = {}
    for _event, entry in ET.iterparse(source, events=("end",)):
        if entry.tag != _TEI + "entry":
            continue
        word = entry.findtext(f"./{_TEI}form/{_TEI}orth", default="").strip().lower()
        if _HEADWORD_PATTERN.fullmatch(word) is not None:
            values = merged.setdefault(word, {"pronunciations": [], "translations": []})
            pronunciations = (
                pronunciation.text.strip()
                for pronunciation in entry.findall(f"./{_TEI}form/{_TEI}pron")
                if pronunciation.text and pronunciation.text.strip()
            )
            translations = (
                "".join(quote.itertext()).strip()
                for quote in entry.findall(
                    f'.//{_TEI}cit[@type="trans"]/{_TEI}quote'
                )
            )
            _extend_unique(values["pronunciations"], pronunciations)
            _extend_unique(
                values["translations"],
                (
                    translation
                    for translation in translations
                    if translation and _CHINESE_PATTERN.search(translation)
                ),
            )
        entry.clear()

    return {
        word: DictionaryEntry(
            pronunciations=tuple(values["pronunciations"]),
            translations=tuple(values["translations"]),
        )
        for word, values in merged.items()
    }


def parse_ecdict_csv(source: TextIO) -> dict[str, TaggedHeadword]:
    reader = csv.DictReader(source)
    required = {"word", "tag", "frq", "bnc"}
    missing = required - set(reader.fieldnames or ())
    if missing:
        raise ValueError(f"ECDICT source is missing columns: {sorted(missing)}")

    headwords: dict[str, TaggedHeadword] = {}
    for row in reader:
        tags = set((row.get("tag") or "").lower().split())
        if not {"cet4", "cet6"} & tags:
            continue
        word = (row.get("word") or "").strip().lower()
        if _HEADWORD_PATTERN.fullmatch(word) is None:
            continue
        level = "CET4" if "cet4" in tags else "CET6"
        candidate = TaggedHeadword(
            word=word,
            level=level,
            frequency=_frequency_score(row),
            phonetic=_normalize_phonetic(row.get("phonetic") or ""),
            translation=_normalize_translation(row.get("translation") or ""),
        )
        current = headwords.get(word)
        if current is None:
            headwords[word] = candidate
        elif candidate.level == "CET4" or current.level != "CET4":
            headwords[word] = TaggedHeadword(
                word=word,
                level="CET4" if "CET4" in {current.level, candidate.level} else "CET6",
                frequency=max(current.frequency, candidate.frequency),
                phonetic=candidate.phonetic or current.phonetic,
                translation=candidate.translation or current.translation,
            )
    return headwords


def build_rows(
    headwords: dict[str, TaggedHeadword],
    dictionary: dict[str, DictionaryEntry],
    *,
    daily_new_words: int = 20,
) -> list[dict[str, str | int]]:
    if daily_new_words <= 0:
        raise ValueError("daily_new_words must be positive")
    by_level: dict[str, list[dict[str, str | int]]] = {"CET4": [], "CET6": []}
    for word, headword in headwords.items():
        entry = dictionary.get(word)
        if entry is None or not entry.pronunciations or not entry.translations:
            continue
        if not headword.phonetic or not headword.translation:
            continue
        by_level[headword.level].append(
            {
                "word": word,
                "phonetic": headword.phonetic,
                "meaning": headword.translation,
                "example": "",
                "level": headword.level,
                "frequency": headword.frequency,
                "initial_delay_days": 0,
            }
        )

    output: list[dict[str, str | int]] = []
    for level in ("CET4", "CET6"):
        rows = sorted(
            by_level[level],
            key=lambda row: (-int(row["frequency"]), str(row["word"])),
        )
        for index, row in enumerate(rows):
            row["initial_delay_days"] = index // daily_new_words
        output.extend(rows)
    return output


def build_artifact(
    ecdict_path: Path,
    freedict_archive: Path,
    output_path: Path,
    provenance_path: Path,
    *,
    daily_new_words: int = 20,
) -> dict[str, object]:
    _verify_file(ecdict_path, "sha256", ECDICT_SHA256)
    _verify_file(freedict_archive, "sha512", FREEDICT_SHA512)
    with ecdict_path.open("r", encoding="utf-8", newline="") as source:
        headwords = parse_ecdict_csv(source)
    curated_words = _load_curated_headwords(CURATED_SOURCE)
    headwords = {
        word: entry for word, entry in headwords.items() if word not in curated_words
    }
    with tarfile.open(freedict_archive, mode="r:xz") as archive:
        member = archive.getmember(FREEDICT_TEI_MEMBER)
        extracted = archive.extractfile(member)
        if extracted is None:
            raise ValueError("FreeDict archive does not contain its TEI source")
        with extracted:
            dictionary = parse_freedict_tei(extracted)

    rows = build_rows(headwords, dictionary, daily_new_words=daily_new_words)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=_OUTPUT_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    level_counts = {
        level: sum(row["level"] == level for row in rows)
        for level in ("CET4", "CET6")
    }
    provenance: dict[str, object] = {
        "schema_version": 1,
        "artifact": {
            "file": output_path.name,
            "sha256": _file_digest(output_path, "sha256"),
            "rows": len(rows),
            "level_counts": level_counts,
            "daily_new_words_per_level": daily_new_words,
            "excluded_curated_overrides": len(curated_words),
        },
        "license": {
            "spdx": "CC-BY-SA-3.0",
            "url": "https://creativecommons.org/licenses/by-sa/3.0/",
        },
        "sources": [
            {
                "name": "ECDICT",
                "url": ECDICT_URL,
                "revision": ECDICT_REVISION,
                "sha256": ECDICT_SHA256,
                "license": "MIT",
                "usage": "headwords, CET tags, frequency ranks, IPA, and Chinese meanings",
            },
            {
                "name": "FreeDict eng-zho",
                "url": FREEDICT_URL,
                "version": FREEDICT_VERSION,
                "sha512": FREEDICT_SHA512,
                "license": "CC-BY-SA-3.0",
                "usage": "independent open-dictionary headword and bilingual-entry validation",
            },
        ],
    }
    provenance_path.parent.mkdir(parents=True, exist_ok=True)
    provenance_path.write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return provenance


def _download_verified(
    url: str,
    destination: Path,
    algorithm: str,
    expected_digest: str,
) -> None:
    hasher = hashlib.new(algorithm)
    with httpx.stream(
        "GET", url, follow_redirects=True, timeout=120.0
    ) as response:
        response.raise_for_status()
        with destination.open("wb") as output:
            for chunk in response.iter_bytes():
                hasher.update(chunk)
                output.write(chunk)
    if hasher.hexdigest() != expected_digest:
        destination.unlink(missing_ok=True)
        raise ValueError(f"Downloaded source failed {algorithm} verification")


def _verify_file(path: Path, algorithm: str, expected_digest: str) -> None:
    if _file_digest(path, algorithm) != expected_digest:
        raise ValueError(f"{path.name} failed {algorithm} verification")


def _file_digest(path: Path, algorithm: str) -> str:
    hasher = hashlib.new(algorithm)
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _frequency_score(row: dict[str, str]) -> int:
    ranks: list[int] = []
    for field in ("frq", "bnc"):
        try:
            rank = int(row.get(field) or 0)
        except ValueError:
            continue
        if rank > 0:
            ranks.append(rank)
    if not ranks:
        return 0
    return max(1, 10_000 - min(min(ranks), 9_999))


def _load_curated_headwords(path: Path) -> set[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        return {
            (row.get("word") or "").strip().lower()
            for row in csv.DictReader(source)
            if (row.get("word") or "").strip()
        }


def _compact_translations(translations: Sequence[str]) -> str:
    selected: list[str] = []
    total_length = 0
    for raw_value in translations:
        value = " ".join(raw_value.split())
        if not value or value in selected:
            continue
        added_length = len(value) + (1 if selected else 0)
        if selected and total_length + added_length > 240:
            break
        if not selected and len(value) > 240:
            value = value[:240].rstrip()
            added_length = len(value)
        selected.append(value)
        total_length += added_length
        if len(selected) == 8:
            break
    return "；".join(selected)


def _normalize_phonetic(raw_value: str) -> str:
    value = " ".join(raw_value.split()).replace("ә", "ə").strip("/[] ")
    return f"/{value}/" if value else ""


def _normalize_translation(raw_value: str) -> str:
    lines = raw_value.replace("\\n", "\n").splitlines()
    general = [
        " ".join(line.split())
        for line in lines
        if line.strip() and not line.lstrip().startswith("[")
    ]
    return _compact_translations(general)


def _extend_unique(target: list[str], values: Iterable[str]) -> None:
    for value in values:
        if value not in target:
            target.append(value)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ecdict-source", type=Path)
    parser.add_argument("--freedict-source", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--provenance-output", type=Path)
    parser.add_argument("--daily-new-words", type=int, default=20)
    arguments = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="cet-agent-vocabulary-") as temp_name:
        temp_dir = Path(temp_name)
        ecdict_path = arguments.ecdict_source or temp_dir / "ecdict.csv"
        freedict_path = arguments.freedict_source or temp_dir / "freedict.tar.xz"
        if arguments.ecdict_source is None:
            _download_verified(ECDICT_URL, ecdict_path, "sha256", ECDICT_SHA256)
        if arguments.freedict_source is None:
            _download_verified(
                FREEDICT_URL,
                freedict_path,
                "sha512",
                FREEDICT_SHA512,
            )
        provenance = build_artifact(
            ecdict_path,
            freedict_path,
            arguments.output,
            arguments.provenance_output
            or arguments.output.with_suffix(".provenance.json"),
            daily_new_words=arguments.daily_new_words,
        )
    artifact = provenance["artifact"]
    assert isinstance(artifact, dict)
    print(
        "Built open CET vocabulary:",
        f"rows={artifact['rows']}",
        f"levels={artifact['level_counts']}",
        f"sha256={artifact['sha256']}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
