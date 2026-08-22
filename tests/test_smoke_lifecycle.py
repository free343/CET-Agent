from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from app.config import PROJECT_ROOT


def test_smoke_process_exits_after_deferred_worker_close(tmp_path: Path) -> None:
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    environment["DATABASE_URL"] = (
        f"sqlite:///{(tmp_path / 'smoke-lifecycle.db').as_posix()}"
    )

    result = subprocess.run(
        [sys.executable, "main.py", "--smoke-test"],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
