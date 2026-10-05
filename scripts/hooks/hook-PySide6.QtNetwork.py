"""仅保留 Windows 原生网络后端；本程序仅用本地 IPC。"""
from pathlib import Path
from PyInstaller.utils.hooks.qt import add_qt6_dependencies

hiddenimports, binaries, datas = add_qt6_dependencies(__file__)
binaries = [entry for entry in binaries if Path(entry[0]).name.casefold() != "qopensslbackend.dll"]
