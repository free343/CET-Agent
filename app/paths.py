"""Resolve read-only resources separately from writable application state."""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

APP_DIRECTORY_NAME = "CET-Agent"


@dataclass(frozen=True, slots=True)
class ApplicationPaths:
    resource_root: Path
    runtime_root: Path
    env_file: Path
    database_file: Path
    log_dir: Path


def resolve_application_paths(
    *,
    frozen: bool | None = None,
    bundle_root: Path | None = None,
    source_root: Path | None = None,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
    platform: str | None = None,
) -> ApplicationPaths:
    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    source = source_root or Path(__file__).resolve().parent.parent
    if is_frozen:
        resource_root = bundle_root or Path(
            getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent)
        )
        environment = os.environ if environ is None else environ
        user_home = Path.home() if home is None else home
        current_platform = sys.platform if platform is None else platform
        runtime_root = _user_data_root(environment, user_home, current_platform)
    else:
        resource_root = source
        runtime_root = source
    return ApplicationPaths(
        resource_root=resource_root,
        runtime_root=runtime_root,
        env_file=runtime_root / ".env",
        database_file=runtime_root / "data" / "cet_agent.db",
        log_dir=runtime_root / "logs",
    )


def _user_data_root(
    environ: Mapping[str, str],
    home: Path,
    platform: str,
) -> Path:
    local_app_data = environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        return Path(local_app_data) / APP_DIRECTORY_NAME
    if platform == "win32":
        return home / "AppData" / "Local" / APP_DIRECTORY_NAME
    xdg_data_home = environ.get("XDG_DATA_HOME", "").strip()
    base = Path(xdg_data_home) if xdg_data_home else home / ".local" / "share"
    return base / APP_DIRECTORY_NAME


APPLICATION_PATHS = resolve_application_paths()
