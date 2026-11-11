# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build for the isolated Pharmacy Management System TEST release.

This is a separate release from ``pharmacy_management.spec``; it never
replaces or modifies the production/1.0.0 build.

Build from the project root with the project virtualenv active::

    .venv\\Scripts\\python.exe -m PyInstaller build\\windows\\pharmacy_management_test.spec --noconfirm

Output: ``dist\\PharmacyManagementSystem_Test\\PharmacyManagementSystem_Test.exe``
(--onedir).

Packaging contract (see docs/test_release_build_report.md):
  - The verified staging snapshot is bundled read-only as
    ``_internal\\seed\\pharmacy_staging.db``.
  - No normal database is bundled: nothing from ``data/``.
  - On first launch the EXE copies the snapshot with SQLite's backup API to
    ``%LOCALAPPDATA%\\PharmacyManagementSystem-Test\\pharmacy.db`` and opens
    that file. Existing test databases are never overwritten.
  - The entry point is ``release_test_main.py``; it removes staging branding
    and adds the "(Test Build)" version designation.
"""

import os
from pathlib import Path

PROJECT_ROOT = Path(SPECPATH).resolve().parent.parent
SEED_DB = PROJECT_ROOT / "staging" / "pharmacy_staging.db"
VERSION_FILE = Path(SPECPATH) / "PharmacyManagementSystem_Test_version.txt"

if not SEED_DB.is_file():
    raise SystemExit(
        f"[TEST RELEASE] Bundled seed database not found: {SEED_DB}\n"
        "Refusing to build a test release without the verified staging snapshot."
    )

APP_NAME = "PharmacyManagementSystem_Test"
block_cipher = None


a = Analysis(
    [str(PROJECT_ROOT / "release_test_main.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=[
        # Bundled read-only seed.  It is never opened for writing: the EXE
        # copies it into the per-user test folder on first launch.
        (str(SEED_DB), "seed"),
    ],
    hiddenimports=[
        # The application entry point is imported inside a function after the
        # test branding is applied, so name it explicitly.
        "main",
        # Lazily imported inside functions; keep them even if static
        # analysis already finds them.
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
        # Heavy stdlib/GUI extras the app never imports.
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
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # GUI application: no console window.
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
    version=str(VERSION_FILE) if VERSION_FILE.is_file() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)
