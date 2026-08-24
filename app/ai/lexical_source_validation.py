"""Strict source-rights and integrity gates for offline lexical inputs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse

from pydantic import ValidationError

from app.ai.schemas import LexicalSourceContract, LexicalSourceManifest


class LexicalSourceDataError(ValueError):
    """Raised when a lexical source contract or pinned file is unsafe."""


def validate_lexical_source_manifest(manifest: LexicalSourceManifest) -> list[str]:
    errors: list[str] = []
    seen_ids: set[str] = set()
    seen_filenames: set[str] = set()
    for source in manifest.sources:
        if source.source_id in seen_ids:
            errors.append(f"duplicate source_id: {source.source_id}")
        seen_ids.add(source.source_id)
        if source.filename.casefold() in seen_filenames:
            errors.append(f"duplicate source filename: {source.filename}")
        seen_filenames.add(source.filename.casefold())

        if not _is_https_url(source.url):
            errors.append(f"{source.source_id}: source URL must use HTTPS")
        if not _is_https_url(source.license.reference):
            errors.append(f"{source.source_id}: license reference must use HTTPS")
        if len(source.approved_uses) != len(set(source.approved_uses)):
            errors.append(f"{source.source_id}: approved_uses contains duplicates")
        if len(source.attribution) != len(set(source.attribution)):
            errors.append(f"{source.source_id}: attribution contains duplicates")
        if any(not value.strip() for value in source.attribution):
            errors.append(f"{source.source_id}: attribution cannot be blank")

        if source.review_status == "approved":
            terms = source.license
            if not (
                terms.redistribution and terms.modification and terms.commercial_use
            ):
                errors.append(
                    f"{source.source_id}: approved source lacks required reuse rights"
                )
            if not source.approved_uses:
                errors.append(
                    f"{source.source_id}: approved source has no approved use"
                )
            if terms.notice_required and not source.attribution:
                errors.append(
                    f"{source.source_id}: required attribution/notice is missing"
                )
        elif source.approved_uses:
            errors.append(
                f"{source.source_id}: non-approved source cannot expose approved uses"
            )
    return errors


def load_lexical_source_manifest(path: Path) -> LexicalSourceManifest:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        manifest = LexicalSourceManifest.model_validate(payload)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise LexicalSourceDataError(
            f"{path.name} violates the lexical-source contract"
        ) from exc
    errors = validate_lexical_source_manifest(manifest)
    if errors:
        raise LexicalSourceDataError(
            f"{path.name} failed source-policy validation: {'; '.join(errors)}"
        )
    return manifest


def source_file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_lexical_source_file(source: LexicalSourceContract, path: Path) -> None:
    if not path.is_file():
        raise LexicalSourceDataError(
            f"{source.source_id}: expected source file is missing: {path}"
        )
    observed = source_file_sha256(path)
    if observed != source.sha256:
        raise LexicalSourceDataError(
            f"{source.source_id}: SHA-256 mismatch for {path.name}"
        )


def _is_https_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.netloc)
