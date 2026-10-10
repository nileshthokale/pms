# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build for Pharmacy Management System v1.0.0 (Windows, onedir).

Reproducible first testing release configuration.

Build from the project root with the project virtualenv active::

    .venv\\Scripts\\python.exe -m PyInstaller build\\windows\\pharmacy_management.spec --noconfirm

Output: ``dist\\PharmacyManagement\\PharmacyManagement.exe`` (--onedir).

Packaging contract (see docs/windows_build_1.0.0.md):
  - No ``*.db`` / ``theme.json`` / ``last_backup.json`` is bundled. The EXE
    creates ``%LOCALAPPDATA%\\PharmacyManagementSystem\\pharmacy.db`` (plus
    theme/backups) on first launch via ``database.connection.get_app_data_dir``.
  - No ``--onefile``: this release is ``--onedir`` (via ``COLLECT`` below).
  - Qt platform + printsupport plugins are collected automatically by the
    PySide6 hooks; ``QtPrintSupport``/``openpyxl`` are also listed as hidden
    imports because parts of the app import them lazily inside functions.
"""

import os
from pathlib import Path

PROJECT_ROOT = Path(SPECPATH).resolve().parent.parent
APP_VERSION = "1.0.0"

block_cipher = None


a = Analysis(
    [str(PROJECT_ROOT / "main.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=[
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
    name="PharmacyManagement",
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
    icon=None,  # No application icon exists in the repo yet.
    version=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="PharmacyManagement",
)
