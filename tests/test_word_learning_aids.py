"""Deterministic tests for the word learning-aid generator and its contracts.

All provider behaviour is faked; these tests never touch the network.
"""

from __future__ import annotations

import json

import pytest

from app.ai.llm_provider import LLMUnavailableError
from app.ai.prompts import word_learning_aids_messages
from app.ai.schemas import (
    WORD_LEARNING_AIDS_PROMPT_VERSION,
    WordLearningAidRecord,
)
from scripts.generate_word_learning_aids import (
    DEFAULT_MAX_OUTPUT_TOKENS,
    DEFAULT_MODEL,
    PromotionError,
    _make_response_logger,
    align_batch,
    assemble_record,
    create_generation_provider,
    generate,
    load_generation_environment,
    parse_batch,
    parse_model_output,
    promote,
)
from scripts.validate_word_learning_aids import SourceEntry

SECRET = "sk-test-secret-key"


class FakeProvider:
    def __init__(self, handler) -> None:
        self.handler = handler
        self.calls = 0

    def generate(self, messages, response_schema=None) -> str:
        self.calls += 1
        return self.handler(messages)


def test_generation_environment_loads_project_dotenv_without_overriding_process_env(
    monkeypatch,
    tmp_path,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "DEEPSEEK_API_KEY=dotenv-secret\nDEEPSEEK_MODEL=dotenv-model\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("DEEPSEEK_MODEL", "process-model")

    load_generation_environment(env_file)

    assert __import__("os").environ["DEEPSEEK_API_KEY"] == "dotenv-secret"
    assert __import__("os").environ["DEEPSEEK_MODEL"] == "process-model"


def test_generation_provider_uses_current_model_json_mode_and_large_budget() -> None:
    provider = create_generation_provider(
        "https://api.deepseek.com",
        DEFAULT_MODEL,
        "secret",
        DEFAULT_MAX_OUTPUT_TOKENS,
    )

    assert DEFAULT_MODEL == "deepseek-v4-flash"
    assert provider.json_output is True
    assert provider.disable_thinking is True
    assert provider.max_output_tokens == 8_192


def test_response_logger_creates_checkpoint_parent_before_first_response(
    tmp_path,
) -> None:
    response_file = tmp_path / "nested" / "responses.jsonl"
    logger = _make_response_logger(response_file)
    assert logger is not None

    logger('{"items": []}')

    assert response_file.exists()
    assert '"raw": "{\\"items\\": []}"' in response_file.read_text(encoding="utf-8")


def _input_items(messages):
    for message in messages:
        content = message.get("content", "")
        if "INPUT:" not in content:
            continue
        after = content.split("INPUT:\n", 1)[1]
        raw = after.split("\n\nJSON_SCHEMA", 1)[0]
        return json.loads(raw)["items"]
    return []


def _valid_generation(item) -> dict:
    word = item["word"]
    existing = item.get("existing_example", "")
    example = (
        existing if existing else f"Students carefully learn {word} in class today."
    )
    return {
        "word": word,
        "example": example,
        "example_translation": f"{word} 的例句翻译。",
        "collocations": [
            {"phrase": f"{word} phrase", "meaning": "搭配一"},
            {"phrase": f"common {word}", "meaning": "常用搭配"},
        ],
        "word_family": [],
    }


def _valid_batch_handler(messages) -> str:
    items = _input_items(messages)
    return json.dumps(
        {"items": [_valid_generation(item) for item in items]},
        ensure_ascii=False,
    )


def _make_sources(words) -> tuple[list[SourceEntry], dict[str, SourceEntry]]:
    ordered = []
    by_word = {}
    for index, word in enumerate(words):
        entry = SourceEntry(
            word=word,
            level="CET4" if index % 2 == 0 else "CET6",
            meaning=f"{word} 的释义",
            example=f"Curated sentence with {word} inside." if index == 0 else "",
            source_kind="curated" if index == 0 else "open",
        )
        ordered.append(entry)
        by_word[word] = entry
    return ordered, by_word


def _record_for(entry: SourceEntry, model: str = "deepseek-chat") -> dict:
    curated = entry.source_kind == "curated"
    example = (
        entry.example
        if curated
        else f"Students carefully learn {entry.word} in class today."
    )
    return {
        "schema_version": 1,
        "word": entry.word,
        "level": entry.level,
        "source_kind": entry.source_kind,
        "source_meaning": entry.meaning,
        "example": example,
        "example_translation": f"{entry.word} 的例句翻译。",
        "example_origin": "curated" if curated else "ai_generated",
        "collocations": [
            {"phrase": f"{entry.word} phrase", "meaning": "搭配一"},
            {"phrase": f"common {entry.word}", "meaning": "常用搭配"},
        ],
        "word_family": [],
        "generator": {
            "provider": "deepseek",
            "model": model,
            "prompt_version": WORD_LEARNING_AIDS_PROMPT_VERSION,
        },
        "content_status": "ai_generated_unreviewed",
    }


def test_parse_model_output_strips_code_fences() -> None:
    payload = parse_model_output('```json\n{"items": []}\n```')
    assert payload == {"items": []}
    assert parse_model_output('{"items": []}') == {"items": []}


def test_parse_model_output_rejects_non_object() -> None:
    with pytest.raises(TypeError):
        parse_model_output("[1, 2, 3]")
    with pytest.raises(ValueError):
        parse_model_output("not json at all")


def test_align_batch_returns_source_order() -> None:
    sources = _make_sources(["alpha", "beta", "gamma"])[0]
    generations = parse_batch(
        {"items": [_valid_generation({"word": w}) for w in ("gamma", "alpha", "beta")]}
    )
    aligned = align_batch(sources, generations)
    assert [gen.word for gen in aligned] == ["alpha", "beta", "gamma"]


@pytest.mark.parametrize(
    "words",
    [
        ["alpha", "beta"],  # missing gamma
        ["alpha", "beta", "gamma", "delta"],  # extra delta
        ["alpha", "beta", "beta"],  # duplicate beta
    ],
)
def test_align_batch_rejects_word_multiset_mismatch(words) -> None:
    sources = _make_sources(["alpha", "beta", "gamma"])[0]
    generations = parse_batch(
        {"items": [_valid_generation({"word": w}) for w in words]}
    )
    with pytest.raises(ValueError):
        align_batch(sources, generations)


def test_assemble_record_preserves_curated_example_exactly() -> None:
    _ordered, by_word = _make_sources(["alpha", "beta"])
    curated = by_word["alpha"]
    generation = parse_batch({"items": [_valid_generation({"word": "alpha"})]})[0]
    record = assemble_record(curated, generation, "deepseek-chat")
    assert record["example"] == "Curated sentence with alpha inside."
    assert record["example_origin"] == "curated"
    assert record["source_meaning"] == "alpha 的释义"


def test_assemble_record_uses_generated_example_for_open() -> None:
    _ordered, by_word = _make_sources(["alpha", "beta"])
    open_entry = by_word["beta"]
    generation = parse_batch({"items": [_valid_generation({"word": "beta"})]})[0]
    record = assemble_record(open_entry, generation, "deepseek-chat")
    assert record["example"] == "Students carefully learn beta in class today."
    assert record["example_origin"] == "ai_generated"


def test_record_schema_forbids_extra_fields() -> None:
    record = _record_for(_make_sources(["alpha"])[1]["alpha"])
    record["unexpected"] = "nope"
    with pytest.raises(ValueError):
        WordLearningAidRecord.model_validate(record)


def test_prompt_uses_stable_version_and_includes_input() -> None:
    messages = word_learning_aids_messages(
        [
            {
                "word": "alpha",
                "meaning": "释义",
                "level": "CET4",
                "source_kind": "open",
                "existing_example": "",
            }
        ]
    )
    assert messages[0]["role"] == "system"
    assert "INPUT:" in messages[1]["content"]
    assert "alpha" in messages[1]["content"]


def test_request_retries_then_succeeds(tmp_path) -> None:
    ordered, by_word = _make_sources(["alpha"])
    attempts = {"count": 0}

    def handler(messages):
        attempts["count"] += 1
        if attempts["count"] == 1:
            return "not valid json"
        return _valid_batch_handler(messages)

    provider = FakeProvider(handler)
    summary = generate(
        provider,
        ordered,
        by_word,
        checkpoint_file=tmp_path / "partial.jsonl",
        failures_file=tmp_path / "failures.jsonl",
        model="deepseek-chat",
        batch_size=20,
        max_retries=2,
        rate_limit_seconds=0,
        sleep_fn=lambda _s: None,
    )
    assert summary.completed == 1
    assert summary.failed == 0
    assert provider.calls == 2


def test_request_exhausts_retries_and_fails_batch(tmp_path) -> None:
    ordered, by_word = _make_sources(["alpha", "beta"])

    def handler(messages):
        # Always return structurally invalid output.
        return "this is not json"

    provider = FakeProvider(handler)
    summary = generate(
        provider,
        ordered,
        by_word,
        checkpoint_file=tmp_path / "partial.jsonl",
        failures_file=tmp_path / "failures.jsonl",
        model="deepseek-chat",
        batch_size=20,
        max_retries=1,
        rate_limit_seconds=0,
        sleep_fn=lambda _s: None,
    )
    assert summary.completed == 0
    assert summary.failed == 2
    assert (tmp_path / "failures.jsonl").exists()
    failures = (tmp_path / "failures.jsonl").read_text(encoding="utf-8")
    assert "alpha" in failures and "beta" in failures


def test_generate_resumes_from_checkpoint_without_recalling(tmp_path) -> None:
    ordered, by_word = _make_sources(["alpha", "beta"])
    checkpoint = tmp_path / "partial.jsonl"
    # Pre-seed alpha as already validated.
    with checkpoint.open("w", encoding="utf-8") as out:
        out.write(json.dumps(_record_for(by_word["alpha"]), ensure_ascii=False) + "\n")

    provider = FakeProvider(_valid_batch_handler)
    summary = generate(
        provider,
        ordered,
        by_word,
        checkpoint_file=checkpoint,
        failures_file=tmp_path / "failures.jsonl",
        model="deepseek-chat",
        batch_size=20,
        max_retries=1,
        rate_limit_seconds=0,
        sleep_fn=lambda _s: None,
    )
    assert summary.completed == 2
    # Only beta needed a request, so exactly one provider call was made.
    assert provider.calls == 1


def test_generate_rejects_checkpoint_from_a_different_model(tmp_path) -> None:
    ordered, by_word = _make_sources(["alpha", "beta"])
    checkpoint = tmp_path / "partial.jsonl"
    checkpoint.write_text(
        json.dumps(
            _record_for(by_word["alpha"], model="different-model"),
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    provider = FakeProvider(_valid_batch_handler)

    with pytest.raises(ValueError, match="checkpoint.*model"):
        generate(
            provider,
            ordered,
            by_word,
            checkpoint_file=checkpoint,
            failures_file=tmp_path / "failures.jsonl",
            model="deepseek-v4-flash",
            rate_limit_seconds=0,
            sleep_fn=lambda _s: None,
        )

    assert provider.calls == 0


def test_generate_force_word_requeries_validated_word(tmp_path) -> None:
    ordered, by_word = _make_sources(["alpha", "beta"])
    checkpoint = tmp_path / "partial.jsonl"
    with checkpoint.open("w", encoding="utf-8") as out:
        for entry in ordered:
            out.write(json.dumps(_record_for(entry), ensure_ascii=False) + "\n")

    provider = FakeProvider(_valid_batch_handler)
    summary = generate(
        provider,
        ordered,
        by_word,
        checkpoint_file=checkpoint,
        failures_file=tmp_path / "failures.jsonl",
        model="deepseek-chat",
        batch_size=20,
        max_retries=1,
        rate_limit_seconds=0,
        force_words=["alpha"],
        sleep_fn=lambda _s: None,
    )
    assert summary.completed == 2
    assert provider.calls == 1


def test_generate_isolates_a_missing_word(tmp_path) -> None:
    ordered, by_word = _make_sources(["alpha", "beta"])

    def handler(messages):
        items = _input_items(messages)
        if len(items) == 2:
            # Batch response is missing beta -> triggers per-word isolation.
            return json.dumps(
                {"items": [_valid_generation(items[0])]},
                ensure_ascii=False,
            )
        return _valid_batch_handler(messages)

    provider = FakeProvider(handler)
    summary = generate(
        provider,
        ordered,
        by_word,
        checkpoint_file=tmp_path / "partial.jsonl",
        failures_file=tmp_path / "failures.jsonl",
        model="deepseek-chat",
        batch_size=20,
        max_retries=1,
        rate_limit_seconds=0,
        sleep_fn=lambda _s: None,
    )
    assert summary.completed == 2
    assert summary.failed == 0


def test_transport_unavailable_is_retried(tmp_path) -> None:
    ordered, by_word = _make_sources(["alpha"])
    attempts = {"count": 0}

    def handler(messages):
        attempts["count"] += 1
        if attempts["count"] < 2:
            raise LLMUnavailableError("temporary")
        return _valid_batch_handler(messages)

    provider = FakeProvider(handler)
    summary = generate(
        provider,
        ordered,
        by_word,
        checkpoint_file=tmp_path / "partial.jsonl",
        failures_file=tmp_path / "failures.jsonl",
        model="deepseek-chat",
        batch_size=20,
        max_retries=2,
        rate_limit_seconds=0,
        sleep_fn=lambda _s: None,
    )
    assert summary.completed == 1


def test_promote_blocks_on_incomplete(tmp_path) -> None:
    ordered, by_word = _make_sources(["alpha", "beta", "gamma"])
    records = {word: _record_for(by_word[word]) for word in ("alpha", "beta")}
    with pytest.raises(PromotionError):
        promote(
            records,
            ordered,
            by_word,
            output_file=tmp_path / "word_learning_aids.jsonl",
            provenance_file=tmp_path / "provenance.json",
            checkpoint_dir=tmp_path / "build",
            model="deepseek-chat",
        )
    assert not (tmp_path / "word_learning_aids.jsonl").exists()


def test_promote_writes_artifact_provenance_and_sample(tmp_path) -> None:
    ordered, by_word = _make_sources(["alpha", "beta", "gamma"])
    records = {word: _record_for(by_word[word]) for word in ("alpha", "beta", "gamma")}
    output = tmp_path / "word_learning_aids.jsonl"
    provenance = tmp_path / "provenance.json"
    checkpoint_dir = tmp_path / "build"

    promote(
        records,
        ordered,
        by_word,
        output_file=output,
        provenance_file=provenance,
        checkpoint_dir=checkpoint_dir,
        model="deepseek-chat",
    )

    lines = output.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    assert [json.loads(line)["word"] for line in lines] == ["alpha", "beta", "gamma"]
    provenance_data = json.loads(provenance.read_text(encoding="utf-8"))
    assert provenance_data["generator"]["model"] == "deepseek-chat"
    assert provenance_data["stats"]["total"] == 3
    assert (checkpoint_dir / "sample_report.json").exists()


def test_generated_outputs_never_contain_api_key(tmp_path) -> None:
    ordered, by_word = _make_sources(["alpha"])
    records = {"alpha": _record_for(by_word["alpha"])}
    output = tmp_path / "word_learning_aids.jsonl"
    provenance = tmp_path / "provenance.json"
    promote(
        records,
        ordered,
        by_word,
        output_file=output,
        provenance_file=provenance,
        checkpoint_dir=tmp_path / "build",
        model="deepseek-chat",
    )
    combined = output.read_text(encoding="utf-8") + provenance.read_text(
        encoding="utf-8"
    )
    assert SECRET not in combined
    assert "Authorization" not in combined
    assert "Bearer" not in combined
