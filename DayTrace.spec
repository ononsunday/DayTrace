# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path


a = Analysis(
    ['run_daytrace.py'],
    pathex=[],
    binaries=[],
    datas=[('assets/art', 'assets/art')],
    hiddenimports=[],
    hookspath=['scripts/hooks'],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtCharts', 'PySide6.QtPdf', 'PySide6.QtVirtualKeyboard'],
    noarchive=False,
    optimize=0,
)

# Qt 使用 Windows 的 ICU 符号，不能捆绑 PATH 中其他软件带版本后缀的 ICU。
# 排除不使用的 OpenSSL x64 后缀版本，保留 Python 自带的 OpenSSL。
foreign_dependencies = {"icuuc.dll", "libssl-3-x64.dll", "libcrypto-3-x64.dll", "opengl32sw.dll"}
a.binaries = [entry for entry in a.binaries if Path(entry[0]).name.casefold() not in foreign_dependencies
              and not Path(entry[0]).name.casefold().startswith("icudt")]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='DayTrace',
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
    icon=['assets/daytrace.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='DayTrace',
)
