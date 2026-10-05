from pathlib import Path
from PyInstaller.utils.hooks.qt import add_qt6_dependencies

hiddenimports, binaries, datas = add_qt6_dependencies(__file__)
unused = {"qpdf.dll", "qtvirtualkeyboardplugin.dll"}
binaries = [entry for entry in binaries if Path(entry[0]).name.casefold() not in unused]
