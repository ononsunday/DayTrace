"""开发用：核对打包 DLL 的符号依赖，定位版本冲突。需要 pefile。"""
from pathlib import Path
import pefile

root = Path(__file__).resolve().parents[1] / "dist" / "DayTrace" / "_internal"
cache = {}

def exports(path):
    if path not in cache:
        pe = pefile.PE(str(path), fast_load=True, max_symbol_exports=100000)
        pe.parse_data_directories([0])
        cache[path] = {symbol.name for symbol in pe.DIRECTORY_ENTRY_EXPORT.symbols}
    return cache[path]

for file in (root / "PySide6").glob("*.dll"):
    pe = pefile.PE(str(file), fast_load=True, max_symbol_exports=100000)
    pe.parse_data_directories([1])
    for imported in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []):
        target = root / imported.dll.decode()
        if not target.exists():
            target = file.parent / imported.dll.decode()
        if not target.exists():
            target = Path("C:/Windows/System32") / imported.dll.decode()
        if not target.exists():
            continue
        missing = [symbol.name.decode() for symbol in imported.imports if symbol.name and symbol.name not in exports(target)]
        if missing:
            print(file.name, "->", target.name, missing, flush=True)
