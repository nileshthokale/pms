# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build for SINGLE-FILE executable (PharmacyManagement.exe).

Generates a single standalone executable (--onefile) containing:
- Application source code and dependencies (PySide6, openpyxl, etc.)
- All screens, database, and UI submodules
- Production licensing configuration
- No bundled database (uses external/runtime user database)
"""

from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

PROJECT_ROOT = Path(SPECPATH).resolve().parent.parent
APP_NAME = "PharmacyManagement"
block_cipher = None

a = Analysis(
    [str(PROJECT_ROOT / "main.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=[
        (str(PROJECT_ROOT / "licensing" / "config.json"), "licensing"),
    ],
    hiddenimports=[
        "PySide6.QtPrintSupport",
        "openpyxl",
        "openpyxl.cell",
        "openpyxl.styles",
        "openpyxl.utils",
        "openpyxl.workbook",
        "openpyxl.worksheet",
        "licensing",
        "licensing.client",
        "licensing.gate",
        "licensing.protocol",
        "licensing.storage",
        "licensing.qt",
        "licensing.fingerprint",
        "psutil",
        "httpx",
        "cryptography",
    ] + collect_submodules("screens") + collect_submodules("database") + collect_submodules("ui") + collect_submodules("reports") + collect_submodules("core"),
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
)
