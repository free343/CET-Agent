# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


project_root = Path(SPECPATH).parent
data_files = (
    (project_root / "data" / "sample_words.csv", "data"),
    (project_root / "data" / "cet_vocabulary_open.csv", "data"),
    (project_root / "data" / "cet_vocabulary_open.provenance.json", "data"),
    (project_root / "data" / "OPEN_VOCABULARY_LICENSE.md", "data"),
    (project_root / ".env.example", "."),
    (project_root / "README.md", "."),
    (project_root / "THIRD_PARTY_NOTICES.md", "."),
)

a = Analysis(
    [str(project_root / "main.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=[(str(source), target) for source, target in data_files],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "fsrs.optimizer",
        "cv2",
        "matplotlib",
        "numpy",
        "pandas",
        "PIL",
        "pytest",
        "scipy",
        "sklearn",
        "tensorflow",
        "torch",
        "transformers",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="CET-Agent",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="CET-Agent",
)
