"""Safe rotating logging configuration."""

from __future__ import annotations

import logging
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

_CONFIGURE_LOCK = threading.Lock()


def configure_logging(log_dir: Path, level: str = "INFO") -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    with _CONFIGURE_LOCK:
        root = logging.getLogger()
        if root.handlers:
            return
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
        )
        file_handler = RotatingFileHandler(
            log_dir / "cet-agent.log",
            maxBytes=2_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        root.setLevel(getattr(logging, level.upper(), logging.INFO))
        root.addHandler(file_handler)
        root.addHandler(stream_handler)
