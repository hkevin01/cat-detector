# -*- mode: python ; coding: utf-8 -*-
# =============================================================================
# ID:           CAT-DETECTOR-SPEC-001
# Purpose:      PyInstaller spec file — bundles cat_detector.py into a single
#               standalone Windows executable (cat-detector.exe).
# Platform:     Windows x64  (built by CI on windows-latest runner)
# Requirements: pyinstaller>=6.x  pynput>=1.7  winotify>=1.1
# Usage:        pyinstaller --noconfirm cat_detector.spec
# Output:       dist/cat-detector.exe
# =============================================================================

import os

# ---------------------------------------------------------------------------
# Analysis — collect all imports and data for the frozen application
# ---------------------------------------------------------------------------
a = Analysis(
    ['cat_detector.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        # pynput Windows backend (evdev is Linux-only and excluded below)
        'pynput',
        'pynput.keyboard',
        'pynput._util',
        'pynput._util.win32',
        'pynput.keyboard._win32',
        # Windows toast notifications
        'winotify',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Exclude Linux-only and unused heavy packages to keep exe small
    excludes=['evdev', 'tkinter', '_tkinter', 'matplotlib', 'numpy'],
    noarchive=False,
    optimize=0,
)

# ---------------------------------------------------------------------------
# PYZ — compressed archive of all pure-Python modules
# ---------------------------------------------------------------------------
pyz = PYZ(a.pure)

# ---------------------------------------------------------------------------
# Windows version resource file (optional — skipped on non-Windows CI)
# ---------------------------------------------------------------------------
_version_file = os.path.join('installer', 'version_info.txt')
_version_file = _version_file if os.path.isfile(_version_file) else None

# ---------------------------------------------------------------------------
# EXE — onefile executable; console=True so detection log is visible
#        when launched from Command Prompt / PowerShell.
# ---------------------------------------------------------------------------
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='cat-detector',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,          # keep console — users see live detection output
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=_version_file,  # Windows VERSIONINFO resource (if present)
)
