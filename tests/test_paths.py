from __future__ import annotations

from pathlib import Path

from app import config
from app.paths import resolve_application_paths


def test_source_mode_keeps_resources_and_runtime_in_project(tmp_path: Path) -> None:
    source_root = tmp_path / "source"

    paths = resolve_application_paths(frozen=False, source_root=source_root)

    assert paths.resource_root == source_root
    assert paths.runtime_root == source_root
    assert paths.env_file == source_root / ".env"
    assert paths.database_file == source_root / "data" / "cet_agent.db"
    assert paths.log_dir == source_root / "logs"


def test_frozen_windows_mode_uses_bundle_for_resources_and_local_app_data(
    tmp_path: Path,
) -> None:
    bundle_root = tmp_path / "bundle"
    local_app_data = tmp_path / "local-app-data"

    paths = resolve_application_paths(
        frozen=True,
        bundle_root=bundle_root,
        environ={"LOCALAPPDATA": str(local_app_data)},
        home=tmp_path / "home",
        platform="win32",
    )

    assert paths.resource_root == bundle_root
    assert paths.runtime_root == local_app_data / "CET-Agent"
    assert paths.env_file == local_app_data / "CET-Agent" / ".env"
    assert paths.database_file == (
        local_app_data / "CET-Agent" / "data" / "cet_agent.db"
    )


def test_frozen_windows_mode_has_home_fallback(tmp_path: Path) -> None:
    paths = resolve_application_paths(
        frozen=True,
        bundle_root=tmp_path / "bundle",
        environ={},
        home=tmp_path / "home",
        platform="win32",
    )

    assert paths.runtime_root == tmp_path / "home" / "AppData" / "Local" / "CET-Agent"


def test_relative_database_url_uses_runtime_root(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "RUNTIME_ROOT", tmp_path / "runtime")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///custom/state.db")

    assert config._database_url() == (
        f"sqlite:///{(tmp_path / 'runtime' / 'custom' / 'state.db').as_posix()}"
    )
