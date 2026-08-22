"""Small deterministic text helpers."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def stable_json_hash(value: Any) -> str:
    serialized = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

