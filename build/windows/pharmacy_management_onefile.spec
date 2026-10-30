# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build for SINGLE-FILE executable (PharmacyManagementSystem.exe).

Generates a single standalone executable (--onefile) containing:
- Application source code and dependencies (PySide6, openpyxl, etc.)
- Embedded seed database (_internal/seed/pharmacy_staging.db)
- Qt platform and print plugins

When launched, the single executable runs self-contained:
- Extracts required runtimes to a secure temporary directory (_MEIPASS)
- Automatically initializes runtime database on first launch
- Requires zero installation or external folders
"""

from pathlib import Path

PROJECT_ROOT = Path(SPECPATH).resolve().parent.parent
SEED_DB = PROJECT_ROOT / "staging" / "pharmacy_staging.db"
VERSION_FILE = Path(SPECPATH) / "PharmacyManagementSystem_Test_version.txt"

if not SEED_DB.is_file():
    raise SystemExit(f"Seed database not found: {SEED_DB}")

APP_NAME = "PharmacyManagementSystem"
block_cipher = None

a = Analysis(
    [str(PROJECT_ROOT / "release_test_main.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=[
        (str(SEED_DB), "seed"),
    ],
    hiddenimports=[
        "main",
        "PySide6.QtPrintSupport",
        "openpyxl",
        "openpyxl.cell",
        "openpyxl.styles",
        "openpyxl.utils",
        "openpyxl.workbook",
        "openpyxl.worksheet",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "scipy",
        "IPython",
        "notebook",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
    version=str(VERSION_FILE) if VERSION_FILE.is_file() else None,
)
