"""只抓取本程序窗口；原生 Qt 页面与隐藏常驻的集成验收。"""
import json
import os
from pathlib import Path
import sys
import tempfile

os.environ.pop("QT_QPA_PLATFORM", None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QLocale, QTimer
from PySide6.QtWidgets import QApplication
from daytrace.app import DayTraceApplication
from daytrace.core.repository import Repository
from daytrace.ui.main_window import MainWindow
from daytrace.ui.theme import apply_theme


root = Path(__file__).resolve().parents[1]
output = root / "qa-output"
output.mkdir(exist_ok=True)
application = QApplication([])
application.setQuitOnLastWindowClosed(False)
QLocale.setDefault(QLocale(QLocale.Language.Chinese, QLocale.Country.China))
report = {"platform": sys.platform, "qt_platform": application.platformName(), "screenshots_only_own_app": True, "production_database_used": False, "checks": []}
scratch = tempfile.TemporaryDirectory(prefix="daytrace-desktop-")
repository = Repository(Path(scratch.name) / "lifecycle.sqlite3")
controller = DayTraceApplication(application, repository)


def verify_lifecycle():
    try:
        report["checks"].append({"name": "worker_thread_running", "passed": controller.thread.isRunning()})
        report["checks"].append({"name": "tray_available", "passed": controller.window.tray_available})
        controller.window.close()
        report["checks"].append({"name": "close_hides_window", "passed": not controller.window.isVisible()})
        report["checks"].append({"name": "hidden_worker_still_running", "passed": controller.thread.isRunning() and controller.worker.timer.isActive()})
        controller.show()
        # 从新首页实际切换两项模式，检查控件、工作线程和数据库保持一致。
        for mode in ("active", "foreground"):
            controller.window.mode_selector.setCurrentIndex(controller.window.mode_selector.findData(mode))
            report["checks"].append({"name": f"header_mode_{mode}_applies_and_persists", "passed": repository.get_setting("mode", "foreground") == mode and controller.worker.tracker.mode == mode})
        controller.settings_changed({"mode": "active", "idle_threshold_seconds": 300, "poll_interval_seconds": 1, "theme": "light", "autostart": False, "reminder_enabled": False, "reminder_time": "21:30"})
        report["checks"].append({"name": "settings_persist_and_worker_apply", "passed": repository.get_setting("mode") == "active" and controller.worker.tracker.mode == "active" and controller.worker.timer.interval() == 1000})
        controller.settings_changed({"mode": "foreground", "poll_interval_seconds": 2})
        report["checks"].append({"name": "two_modes_switch", "passed": controller.worker.tracker.mode == "foreground"})
        controller.commands.pause.emit(True)
        QTimer.singleShot(100, finish_lifecycle)
    except Exception as error:
        report["error"] = repr(error)
        finish_lifecycle()


def finish_lifecycle():
    report["checks"].append({"name": "pause_command_reaches_worker", "passed": controller.worker.paused})
    # 使用独立空数据库生成发布预览，不把个人记录放入截图或源码。
    gallery_repository = Repository(Path(scratch.name) / "empty.sqlite3")
    window = MainWindow(gallery_repository)
    window.allow_close = True
    window.resize(1180, 820)
    window.show()
    application.processEvents()
    for index in range(6):
        window.show_page(index)
        application.processEvents()
        path = output / f"native-page-{index}.png"
        passed = window.grab().save(str(path))
        report["checks"].append({"name": f"native_page_{index}_renders", "passed": passed})
    window.show_page(0)
    window.theme = "dark"
    apply_theme(window, "dark")
    application.processEvents()
    window.grab().save(str(output / "native-dark.png"))
    window.resize(900, 640)
    for index in (0, 3, 5):
        window.show_page(index)
        application.processEvents()
        window.grab().save(str(output / f"native-small-{index}.png"))
    window.theme = "light"
    apply_theme(window, "light")
    window.show_page(0)
    application.processEvents()
    window.grab().save(str(output / "native-small-light-0.png"))
    window.close()
    gallery_repository.close()
    report["passed"] = all(check["passed"] for check in report["checks"]) and "error" not in report
    (output / "desktop-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    controller.quit()


QTimer.singleShot(2200, verify_lifecycle)
application.exec()
scratch.cleanup()
print(json.dumps({"passed": report.get("passed"), "report": str(output / "desktop-report.json")}), flush=True)
raise SystemExit(0 if report.get("passed") else 1)
