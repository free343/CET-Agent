"""Offline validation for the deterministic level-1 acquisition quiz."""

from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.domain.acquisition import EnglishCandidate, build_cloze_question

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_FILES = (
    PROJECT_ROOT / "data" / "sample_words.csv",
    PROJECT_ROOT / "data" / "cet_vocabulary_open.csv",
)
AID_FILE = PROJECT_ROOT / "data" / "word_learning_aids.jsonl"


def main() -> int:
    source_rows = [
        row
        for path in SOURCE_FILES
        for row in csv.DictReader(path.open(encoding="utf-8-sig", newline=""))
    ]
    candidates_by_level = {
        level: [
            EnglishCandidate(
                word_id=index,
                word=row["word"],
                meaning=row["meaning"],
                frequency=int(row.get("frequency") or 0),
            )
            for index, row in enumerate(source_rows, start=1)
            if row["level"].upper() == level
        ]
        for level in ("CET4", "CET6")
    }
    source_by_word = {
        row["word"]: (index, row) for index, row in enumerate(source_rows, start=1)
    }
    records = [
        json.loads(line)
        for line in AID_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    errors: list[str] = []
    if len(source_rows) != 4_611:
        errors.append(f"expected 4611 source words, got {len(source_rows)}")
    if len(records) != len(source_rows):
        errors.append(f"expected {len(source_rows)} aids, got {len(records)}")

    for record in records:
        word = record.get("word", "")
        source = source_by_word.get(word)
        if source is None:
            errors.append(f"unknown word: {word}")
            continue
        word_id, source_row = source
        level = str(record.get("level", "")).upper()
        target = EnglishCandidate(
            word_id=word_id,
            word=word,
            meaning=source_row["meaning"],
            frequency=int(source_row.get("frequency") or 0),
        )
        question = build_cloze_question(
            target,
            str(record.get("example", "")),
            candidates_by_level.get(level, []),
        )
        if question is None:
            errors.append(f"no four-choice cloze: {word}")
            continue
        if len(question.options) != 4:
            errors.append(f"wrong option count: {word}")
        if sum(option.is_correct for option in question.options) != 1:
            errors.append(f"wrong correct count: {word}")
        if re.search(
            rf"(?<![A-Za-z]){re.escape(word)}(?![A-Za-z])",
            question.text,
            flags=re.IGNORECASE,
        ):
            errors.append(f"answer leaked in cloze: {word}")

    if errors:
        print(f"FAIL: {len(errors)} error(s)")
        print("\n".join(errors[:50]))
        return 1
    print(
        f"PASS: {len(records)} acquisition records produce safe four-choice cloze items"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
