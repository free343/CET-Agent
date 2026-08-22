from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

from app import logging_config


def test_concurrent_configuration_adds_one_handler_pair(
    tmp_path: Path,
    monkeypatch,
) -> None:
    logger = logging.getLogger(f"concurrent-configuration-test-{id(tmp_path)}")
    barrier = Barrier(2)

    monkeypatch.setattr(logging_config.logging, "getLogger", lambda: logger)

    def slow_file_handler(*args, **kwargs):
        time.sleep(0.05)
        return logging.NullHandler()

    monkeypatch.setattr(logging_config, "RotatingFileHandler", slow_file_handler)

    def configure() -> None:
        barrier.wait()
        logging_config.configure_logging(tmp_path)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(configure) for _ in range(2)]
        for future in futures:
            future.result()

    assert len(logger.handlers) == 2
