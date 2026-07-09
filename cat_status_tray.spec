# -*- mode: python ; coding: utf-8 -*-

import os

_icon_file = os.path.join('installer', 'cat-detector-status-tray.ico')
_icon_file = _icon_file if os.path.isfile(_icon_file) else None

a = Analysis(
    ['cat_status_tray.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['pystray', 'PIL', 'PIL.Image', 'PIL.ImageDraw'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['evdev', 'tkinter', '_tkinter', 'matplotlib', 'numpy'],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

_version_file = os.path.join('installer', 'version_info.txt')
_version_file = _version_file if os.path.isfile(_version_file) else None

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='cat-detector-status-tray',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=_version_file,
    icon=_icon_file,
)