"""Compile the unsigned Windows installer from the existing onedir build."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INSTALLER_SCRIPT = PROJECT_ROOT / "packaging" / "CET-Agent.iss"
PACKAGE_EXE = PROJECT_ROOT / "dist" / "CET-Agent" / "CET-Agent.exe"


def compiler_candidates() -> list[Path]:
    candidates: list[Path] = []
    path_compiler = shutil.which("ISCC.exe") or shutil.which("ISCC")
    if path_compiler:
        candidates.append(Path(path_compiler))
    for variable in ("LOCALAPPDATA", "ProgramFiles", "ProgramFiles(x86)"):
        root = os.environ.get(variable, "").strip()
        if not root:
            continue
        candidates.extend(
            (
                Path(root) / "Programs" / "Inno Setup 7" / "ISCC.exe",
                Path(root) / "Programs" / "Inno Setup 6" / "ISCC.exe",
                Path(root) / "Inno Setup 7" / "ISCC.exe",
                Path(root) / "Inno Setup 6" / "ISCC.exe",
            )
        )
    return candidates


def find_compiler(explicit: Path | None = None) -> Path:
    candidates = [explicit] if explicit is not None else compiler_candidates()
    for candidate in candidates:
        if candidate is not None and candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError(
        "Inno Setup compiler not found. Install Inno Setup 6/7 or pass "
        "--compiler C:\\path\\to\\ISCC.exe."
    )


def build_installer(compiler: Path) -> None:
    if not PACKAGE_EXE.is_file():
        raise FileNotFoundError(
            "PyInstaller package is missing; build packaging/CET-Agent.spec first."
        )
    subprocess.run(
        [str(compiler), str(INSTALLER_SCRIPT)],
        cwd=PROJECT_ROOT,
        check=True,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compiler", type=Path)
    args = parser.parse_args(argv)
    compiler = find_compiler(args.compiler)
    print(f"Using Inno Setup compiler: {compiler}")
    build_installer(compiler)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
