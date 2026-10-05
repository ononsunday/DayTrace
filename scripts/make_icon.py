"""只绘制应用图标，不读取屏幕。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from daytrace.app import app_icon

application = QApplication([])
root = Path(__file__).resolve().parents[1]
(root / "assets").mkdir(exist_ok=True)
icon = app_icon()
if not icon.pixmap(64, 64).save(str(root / "assets" / "daytrace.ico"), "ICO"):
    raise RuntimeError("无法写入 ICO 图标")
