"""Resumable batch generator for word learning-aid content via DeepSeek.

The generator reads only the two source CSVs, never the database. It calls the
model one batch at a time, validates every returned word against the source and
the artifact contract, retries structural failures, isolates failing words, and
checkpoints validated records keyed by word. Promotion to the formal
``data/word_learning_aids.jsonl`` happens only after a full offline validation
passes, and the provenance file records the artifact without any secret.

API key handling: the key is read only from ``DEEPSEEK_API_KEY`` (environment or
a local ``.env`` already loaded by the app config) and is never written to any
output file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ai.learning_aid_validation import sanitize_generation
from app.ai.llm_provider import LLMUnavailableError
from app.ai.openai_compatible_provider import OpenAICompatibleProvider
from app.ai.prompts import word_learning_aids_messages
from app.ai.schemas import (
    WORD_LEARNING_AIDS_PROMPT_VERSION,
    WordLearningAidGeneration,
    WordLearningAidGenerationBatch,
    WordLearningAidRecord,
)
from scripts.validate_word_learning_aids import (
    CURATED_CSV,
    OPEN_CSV,
    SourceEntry,
    load_sources,
    validate_record,
    validate_records,
)

DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MAX_OUTPUT_TOKENS = 8_192
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CHECKPOINT_DIR = Path("build") / "word_learning_aids"
DEFAULT_OUTPUT = Path("data") / "word_learning_aids.jsonl"
DEFAULT_PROVENANCE = Path("data") / "word_learning_aids.provenance.json"

_POS_MARKER = re.compile(r"\b(n|v|vt|vi|adj|adv|a|prep|conj|pron|aux|num|art|int)\.")


class BatchGenerationError(RuntimeError):
    """Raised when a batch cannot be generated after all retries."""


class PromotionError(RuntimeError):
    """Raised when the artifact must not be promoted to the formal output."""


def load_generation_environment(env_file: Path = PROJECT_ROOT / ".env") -> None:
    """Load generator credentials without overriding explicit process values."""
    load_dotenv(env_file, override=False)


def create_generation_provider(
    base_url: str,
    model: str,
    api_key: str,
    max_output_tokens: int,
) -> OpenAICompatibleProvider:
    """Create the offline-only JSON Provider without changing chat budgets."""
    return OpenAICompatibleProvider(
        base_url,
        model,
        api_key,
        timeout_seconds=120.0,
        max_output_tokens=max_output_tokens,
        json_output=True,
        disable_thinking=True,
    )


def _bounded_output_tokens(raw: str) -> int:
    value = int(raw)
    if not 1_024 <= value <= 32_768:
        raise argparse.ArgumentTypeError(
            "max output tokens must be between 1024 and 32768"
        )
    return value


@dataclass(slots=True)
class GenerationSummary:
    completed: int
    failed: int
    retries: int
    remaining: int


@dataclass(frozen=True, slots=True)
class PromotionResult:
    artifact_sha256: str
    model: str


def batch_payload(sources: list[SourceEntry]) -> list[dict[str, str]]:
    """Build the exact per-batch model input described by the contract."""
    return [
        {
            "word": item.word,
            "meaning": item.meaning,
            "level": item.level,
            "source_kind": item.source_kind,
            "existing_example": item.example,
        }
        for item in sources
    ]


def parse_model_output(text: str) -> dict[str, object]:
    """Strip code fences and parse the model reply as a JSON object."""
    cleaned = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1).strip()
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError("model output is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise TypeError("model output is not a JSON object")
    return payload


def parse_batch(payload: dict[str, object]) -> list[WordLearningAidGeneration]:
    """Validate the batch reply against the strict generation schema."""
    return WordLearningAidGenerationBatch.model_validate(payload).items


def align_batch(
    sources: list[SourceEntry],
    generations: list[WordLearningAidGeneration],
) -> list[WordLearningAidGeneration]:
    """Return generations in source order; reject missing/extra/duplicate words."""
    source_words = [item.word for item in sources]
    by_word: dict[str, WordLearningAidGeneration] = {}
    for generation in generations:
        if generation.word in by_word:
            raise ValueError(f"duplicate word in model output: {generation.word}")
        by_word[generation.word] = generation
    if set(source_words) != set(by_word):
        missing = sorted(set(source_words) - set(by_word))
        extra = sorted(set(by_word) - set(source_words))
        raise ValueError(f"word multiset mismatch: missing={missing} extra={extra}")
    return [by_word[word] for word in source_words]


def assemble_record(
    source: SourceEntry,
    generation: WordLearningAidGeneration,
    model: str,
) -> dict[str, object]:
    """Assemble one final record, preserving curated examples exactly."""
    curated = source.source_kind == "curated"
    return {
        "schema_version": 1,
        "word": source.word,
        "level": source.level,
        "source_kind": source.source_kind,
        "source_meaning": source.meaning,
        "example": source.example if curated else generation.example,
        "example_translation": generation.example_translation,
        "example_origin": "curated" if curated else "ai_generated",
        "collocations": [item.model_dump() for item in generation.collocations],
        "word_family": [item.model_dump() for item in generation.word_family],
        "generator": {
            "provider": "deepseek",
            "model": model,
            "prompt_version": WORD_LEARNING_AIDS_PROMPT_VERSION,
        },
        "content_status": "ai_generated_unreviewed",
    }


def validate_record_dict(
    record: dict[str, object],
    by_word: dict[str, SourceEntry],
) -> list[str]:
    """Parse and validate one assembled record; return every violation."""
    try:
        model = WordLearningAidRecord.model_validate(record)
    except ValueError as exc:
        return [f"{record.get('word', '?')}: invalid record: {exc}"]
    return validate_record(model, by_word)


def _backoff_seconds(attempt: int) -> float:
    return float(2**attempt)


def _request(
    provider: object,
    sources: list[SourceEntry],
    model: str,
    max_retries: int,
    sleep_fn: Callable[[float], None],
    on_raw_response: Callable[[str], None] | None,
    retry_feedback: str | None = None,
) -> tuple[list[WordLearningAidGeneration], int]:
    """Request one batch with retries; return (aligned generations, retries)."""
    payload_items = batch_payload(sources)
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        messages = word_learning_aids_messages(
            payload_items,
            retry=attempt > 0 or bool(retry_feedback),
            retry_feedback=retry_feedback,
        )
        try:
            text = provider.generate(messages)  # type: ignore[attr-defined]
            if on_raw_response is not None:
                on_raw_response(text)
            generations = parse_batch(parse_model_output(text))
            return align_batch(sources, generations), attempt
        except LLMUnavailableError as exc:
            last_error = exc
        except (ValueError, TypeError) as exc:
            last_error = exc
        if attempt < max_retries:
            sleep_fn(_backoff_seconds(attempt))
    raise BatchGenerationError(
        f"batch failed after {max_retries + 1} attempts: {last_error}"
    )


def _request_single(
    provider: object,
    source: SourceEntry,
    model: str,
    max_retries: int,
    sleep_fn: Callable[[float], None],
    on_raw_response: Callable[[str], None] | None,
    retry_feedback: str | None = None,
) -> tuple[WordLearningAidGeneration | None, int]:
    try:
        generations, retries = _request(
            provider,
            [source],
            model,
            max_retries,
            sleep_fn,
            on_raw_response,
            retry_feedback,
        )
        return generations[0], retries
    except BatchGenerationError:
        return None, max_retries


def _isolate_word(
    provider: object,
    source: SourceEntry,
    by_word: dict[str, SourceEntry],
    model: str,
    max_retries: int,
    sleep_fn: Callable[[float], None],
    on_raw_response: Callable[[str], None] | None,
    initial_feedback: list[str] | None = None,
) -> tuple[dict[str, object] | None, int, str]:
    """Attempt a single-word request; return (record, retries, failure_reason)."""
    total_retries = 0
    feedback = "; ".join(initial_feedback or ())
    for validation_attempt in range(max_retries + 1):
        generation, retries = _request_single(
            provider,
            source,
            model,
            max_retries,
            sleep_fn,
            on_raw_response,
            feedback or None,
        )
        total_retries += retries
        if generation is None:
            return None, total_retries, "single-word generation failed"
        record = assemble_record(source, sanitize_generation(generation), model)
        errors = validate_record_dict(record, by_word)
        if not errors:
            return record, total_retries, ""
        feedback = "; ".join(errors)
        if validation_attempt < max_retries:
            sleep_fn(_backoff_seconds(validation_attempt))
    return None, total_retries, feedback


def _generate_batch(
    provider: object,
    batch: list[SourceEntry],
    by_word: dict[str, SourceEntry],
    model: str,
    max_retries: int,
    sleep_fn: Callable[[float], None],
    on_raw_response: Callable[[str], None] | None,
) -> tuple[dict[str, dict[str, object]], dict[str, str], int]:
    records: dict[str, dict[str, object]] = {}
    failures: dict[str, str] = {}
    total_retries = 0
    try:
        generations, retries = _request(
            provider, batch, model, max_retries, sleep_fn, on_raw_response
        )
        total_retries += retries
    except BatchGenerationError:
        for source in batch:
            record, retries, reason = _isolate_word(
                provider, source, by_word, model, max_retries, sleep_fn, on_raw_response
            )
            total_retries += retries
            if record is None:
                failures[source.word] = reason
            else:
                records[source.word] = record
        return records, failures, total_retries

    for source, generation in zip(batch, generations):
        record = assemble_record(source, sanitize_generation(generation), model)
        errors = validate_record_dict(record, by_word)
        if not errors:
            records[source.word] = record
            continue
        isolated, retries, reason = _isolate_word(
            provider,
            source,
            by_word,
            model,
            max_retries,
            sleep_fn,
            on_raw_response,
            errors,
        )
        total_retries += retries
        if isolated is None:
            failures[source.word] = reason or "; ".join(errors)
        else:
            records[source.word] = isolated
    return records, failures, total_retries


def load_checkpoint(checkpoint_file: Path) -> dict[str, dict[str, object]]:
    if not checkpoint_file.exists():
        return {}
    records: dict[str, dict[str, object]] = {}
    with checkpoint_file.open("r", encoding="utf-8", newline="") as source:
        for raw in source:
            line = raw.rstrip("\r\n")
            if not line.strip():
                continue
            record = json.loads(line)
            records[str(record["word"])] = record
    return records


def load_validated_checkpoint(
    checkpoint_file: Path,
    by_word: dict[str, SourceEntry],
    model: str,
) -> dict[str, dict[str, object]]:
    """Reject corrupt, stale-source, or mixed-model checkpoint records."""
    records = load_checkpoint(checkpoint_file)
    errors: list[str] = []
    for key, raw in records.items():
        if raw.get("word") != key:
            errors.append(f"{key}: checkpoint key does not match record word")
            continue
        errors.extend(validate_record_dict(raw, by_word))
        try:
            parsed = WordLearningAidRecord.model_validate(raw)
        except ValueError:
            continue
        if parsed.generator.model != model:
            errors.append(
                f"{key}: checkpoint model {parsed.generator.model!r} does not "
                f"match requested model {model!r}"
            )
    if errors:
        raise ValueError("checkpoint validation failed: " + "; ".join(errors[:20]))
    return records


def _atomic_write_lines(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as out:
        for line in lines:
            out.write(line)
    os.replace(tmp, path)


def save_checkpoint(
    checkpoint_file: Path,
    records_by_word: dict[str, dict[str, object]],
) -> None:
    _atomic_write_lines(
        checkpoint_file,
        [
            json.dumps(records_by_word[word], ensure_ascii=False) + "\n"
            for word in sorted(records_by_word)
        ],
    )


def save_failures(failures_file: Path, failures: dict[str, str]) -> None:
    _atomic_write_lines(
        failures_file,
        [
            json.dumps({"word": word, "reason": reason}, ensure_ascii=False) + "\n"
            for word, reason in sorted(failures.items())
        ],
    )


def generate(
    provider: object,
    ordered_sources: list[SourceEntry],
    by_word: dict[str, SourceEntry],
    *,
    checkpoint_file: Path,
    failures_file: Path,
    model: str,
    batch_size: int = 20,
    max_retries: int = 2,
    rate_limit_seconds: float = 1.0,
    max_items: int | None = None,
    force_words: list[str] | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    on_raw_response: Callable[[str], None] | None = None,
    on_progress: Callable[[int, int, int, int], None] | None = None,
) -> GenerationSummary:
    records = load_validated_checkpoint(checkpoint_file, by_word, model)
    failures: dict[str, str] = {}
    force = {word.strip().lower() for word in (force_words or ())}
    pending = [
        item
        for item in ordered_sources
        if item.word not in records or item.word in force
    ]
    if max_items is not None:
        pending = pending[: max(0, int(max_items))]

    total_retries = 0
    total = len(pending)
    safe_batch_size = max(1, int(batch_size))
    for index in range(0, total, safe_batch_size):
        batch = pending[index : index + safe_batch_size]
        batch_records, batch_failures, batch_retries = _generate_batch(
            provider, batch, by_word, model, max_retries, sleep_fn, on_raw_response
        )
        total_retries += batch_retries
        records.update(batch_records)
        failures.update(batch_failures)
        save_checkpoint(checkpoint_file, records)
        save_failures(failures_file, failures)
        if on_progress is not None:
            on_progress(
                len(records),
                len(failures),
                len(ordered_sources) - len(records),
                total_retries,
            )
        if rate_limit_seconds > 0:
            sleep_fn(rate_limit_seconds)
    return GenerationSummary(
        completed=len(records),
        failed=len(failures),
        retries=total_retries,
        remaining=len(ordered_sources) - len(records),
    )


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_sample_report(
    records: list[dict[str, object]],
    by_word: dict[str, SourceEntry],
    *,
    sample_size: int = 100,
    seed: int = 20260823,
) -> dict[str, object]:
    """Deterministic random sample plus fixed boundary-category spot checks."""
    record_by_word = {str(record["word"]): record for record in records}
    rng = random.Random(seed)
    sampled_words = rng.sample(
        list(record_by_word), min(sample_size, len(record_by_word))
    )

    def summarize(words: list[str]) -> list[dict[str, object]]:
        result: list[dict[str, object]] = []
        for word in words:
            record = record_by_word.get(word)
            if record is None:
                continue
            errors = validate_record_dict(record, by_word)
            result.append({"word": word, "valid": not errors, "errors": errors})
        return result

    all_words = list(record_by_word)
    multi_pos = [
        word
        for word in all_words
        if len(set(_POS_MARKER.findall(by_word[word].meaning))) >= 3
    ][:10]
    boundary = {
        "multi_pos": summarize(multi_pos),
        "hyphenated": summarize([w for w in all_words if "-" in w][:10]),
        "apostrophe": summarize([w for w in all_words if "'" in w][:10]),
        "long_meaning": summarize(
            [w for w in all_words if len(by_word[w].meaning) >= 40][:10]
        ),
        "empty_word_family": summarize(
            [w for w in all_words if not record_by_word[w].get("word_family")][:10]
        ),
    }
    return {
        "sample_size": len(sampled_words),
        "sampled": summarize(sampled_words),
        "boundary": boundary,
        "note": "deterministic sampled spot-check; not a manual review",
    }


def promote(
    records_by_word: dict[str, dict[str, object]],
    ordered_sources: list[SourceEntry],
    by_word: dict[str, SourceEntry],
    *,
    output_file: Path,
    provenance_file: Path,
    checkpoint_dir: Path,
    model: str,
) -> PromotionResult:
    ordered_records = [
        records_by_word[entry.word]
        for entry in ordered_sources
        if entry.word in records_by_word
    ]
    report = validate_records(
        ordered_records, ordered_sources, by_word, require_complete=True
    )
    if report.errors:
        raise PromotionError(
            f"promotion blocked by {len(report.errors)} validation errors"
        )

    _atomic_write_lines(
        output_file,
        [json.dumps(record, ensure_ascii=False) + "\n" for record in ordered_records],
    )
    artifact_hash = _sha256_file(output_file)
    provenance: dict[str, object] = {
        "generator": {
            "provider": "deepseek",
            "model": model,
            "prompt_version": WORD_LEARNING_AIDS_PROMPT_VERSION,
        },
        "source_files": {
            "sample_words.csv": _sha256_file(CURATED_CSV),
            "cet_vocabulary_open.csv": _sha256_file(OPEN_CSV),
        },
        "artifact": {"path": output_file.name, "sha256": artifact_hash},
        "stats": report.stats,
        "validation": {"result": "passed", "errors": 0},
        "completed_at": datetime.now(UTC).isoformat(),
    }
    provenance_payload = json.dumps(provenance, ensure_ascii=False, indent=2) + "\n"
    _atomic_write_lines(provenance_file, [provenance_payload])

    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    sample_report = build_sample_report(ordered_records, by_word)
    (checkpoint_dir / "sample_report.json").write_text(
        json.dumps(sample_report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return PromotionResult(artifact_sha256=artifact_hash, model=model)


def _make_response_logger(responses_file: Path | None) -> Callable[[str], None] | None:
    if responses_file is None:
        return None
    try:
        responses_file.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None

    def log(text: str) -> None:
        try:
            with responses_file.open("a", encoding="utf-8", newline="") as out:
                out.write(json.dumps({"raw": text[:4000]}, ensure_ascii=False) + "\n")
        except OSError:
            pass

    return log


def _make_progress_printer() -> Callable[[int, int, int, int], None]:
    state = {"printed": 0}

    def progress(completed: int, failed: int, remaining: int, retries: int) -> None:
        if completed - state["printed"] >= 200 or remaining == 0:
            print(
                f"progress: completed={completed} failed={failed} "
                f"remaining={remaining} retries={retries}",
                flush=True,
            )
            state["printed"] = completed

    return progress


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Resumable batch generator for word learning-aid content"
    )
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument(
        "--resume", action="store_true", help="reuse checkpoint (always on)"
    )
    parser.add_argument("--max-items", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--model", default=None)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--checkpoint-dir", default=str(DEFAULT_CHECKPOINT_DIR))
    parser.add_argument("--force-word", action="append", default=None)
    parser.add_argument("--rate-limit", type=float, default=1.0)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument(
        "--max-output-tokens",
        type=_bounded_output_tokens,
        default=DEFAULT_MAX_OUTPUT_TOKENS,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    load_generation_environment()
    args = build_argument_parser().parse_args(argv)
    model = args.model or os.environ.get("DEEPSEEK_MODEL", DEFAULT_MODEL)
    base_url = args.base_url or os.environ.get("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL)
    api_key = os.environ.get("DEEPSEEK_API_KEY")

    ordered_sources, by_word = load_sources()
    checkpoint_dir = Path(args.checkpoint_dir)
    checkpoint_file = checkpoint_dir / "partial.jsonl"
    failures_file = checkpoint_dir / "failures.jsonl"
    responses_file = checkpoint_dir / "responses.jsonl"
    force_words = [
        word
        for group in (args.force_word or ())
        for word in group.split(",")
        if word.strip()
    ]

    if args.dry_run:
        records = load_validated_checkpoint(checkpoint_file, by_word, model)
        force = {word.lower() for word in force_words}
        pending = [
            entry
            for entry in ordered_sources
            if entry.word not in records or entry.word in force
        ]
        if args.max_items is not None:
            pending = pending[: max(0, args.max_items)]
        print(
            f"dry-run: total={len(ordered_sources)} completed={len(records)} "
            f"pending={len(pending)} model={model} batch_size={args.batch_size}"
        )
        return 0

    if not api_key:
        print(
            "ERROR: DEEPSEEK_API_KEY is not set. Add it to a local .env "
            "(or export it) and rerun this command.",
            file=sys.stderr,
        )
        return 2

    provider = create_generation_provider(
        base_url,
        model,
        api_key,
        args.max_output_tokens,
    )
    on_raw_response = _make_response_logger(responses_file)
    summary = generate(
        provider,
        ordered_sources,
        by_word,
        checkpoint_file=checkpoint_file,
        failures_file=failures_file,
        model=model,
        batch_size=args.batch_size,
        max_retries=args.max_retries,
        rate_limit_seconds=args.rate_limit,
        max_items=args.max_items,
        force_words=force_words,
        on_raw_response=on_raw_response,
        on_progress=_make_progress_printer(),
    )
    print(
        f"done: completed={summary.completed} failed={summary.failed} "
        f"retries={summary.retries} remaining={summary.remaining}"
    )

    if summary.remaining == 0 and summary.failed == 0:
        records = load_checkpoint(checkpoint_file)
        try:
            result = promote(
                records,
                ordered_sources,
                by_word,
                output_file=Path(args.output),
                provenance_file=Path(args.output).with_name(
                    "word_learning_aids.provenance.json"
                ),
                checkpoint_dir=checkpoint_dir,
                model=model,
            )
            print(f"promoted: artifact={result.artifact_sha256} model={result.model}")
        except PromotionError as exc:
            print(f"promotion skipped: {exc}", file=sys.stderr)
            return 1
    else:
        print(
            "generation incomplete; rerun with --resume to continue.",
            file=sys.stderr,
        )
    return 0 if summary.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
