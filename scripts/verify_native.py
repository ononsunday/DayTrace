"""在独立临时数据库验证 Windows 前台检测，不修改用户的生产数据库。

只请求本测试创建的两个窗口获得前台焦点，绝不激活用户其他应用。
报告不含用户窗口标题、网址、输入内容或屏幕截图。
"""
from __future__ import annotations

import argparse
import ctypes
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from daytrace.core.models import AppIdentity, Observation
from daytrace.core.repository import Repository
from daytrace.core.tracker import Tracker
from daytrace.platform.windows import WindowsDetector, _NativeApi, executable_identity


def run_unit_tests() -> dict:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_windows.py", "-q"],
        cwd=PROJECT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
    )
    count = re.search(r"(\d+) passed", result.stdout)
    return {"command": "python -m pytest tests/test_windows.py -q", "returncode": result.returncode,
            "passed": int(count.group(1)) if count else 0, "output": result.stdout.strip()}


def verify_gap(path: Path) -> dict:
    repository = Repository(path)
    try:
        tracker = Tracker(repository, max_gap=6)
        app = AppIdentity("native-test-gap", "间隔保护测试")
        wall = datetime.now().astimezone()
        for elapsed in (0, 2, 122, 124):
            tracker.observe(Observation(elapsed, wall + timedelta(seconds=elapsed), app))
        tracker.flush()
        total = repository.daily_summary(wall.date())["total"]
        assert abs(total - 4) < 0.000001, "长间隔被错误累计"
        return {"kind": "simulated_clock_in_real_sqlite", "input_intervals_seconds": [2, 120, 2],
                "saved_seconds": total, "long_gap_discarded": True}
    finally:
        repository.close()


def verify_native_messages() -> dict:
    """给过滤器传入内存中的测试 MSG，不向 Windows 发送系统消息。"""
    from ctypes import wintypes
    from daytrace.app import Commands, NativeEvents

    commands = Commands()
    received = []
    commands.session.connect(received.append)
    events = NativeEvents(commands)
    sequence = [(0x02B1, 7), (0x0218, 4), (0x02B1, 8), (0x0218, 18)]
    for message, value in sequence:
        msg = wintypes.MSG()
        msg.message, msg.wParam = message, value
        events.nativeEventFilter(b"windows_generic_MSG", ctypes.addressof(msg))
    assert received == [False, False, False, True], "系统会话状态组合错误"
    return {"kind": "synthetic_MSG_no_os_event_sent", "sequence": ["LOCK", "SUSPEND", "UNLOCK", "RESUMEAUTOMATIC"],
            "session_available_events": received, "system_lock_or_suspend_performed": False}


def verify_live_service_pause(path: Path) -> dict:
    """真实采样接入服务，临时计时仅落入测试库，完全不切换前台窗口。"""
    from daytrace.service import TrackingWorker

    repository = Repository(path)
    worker = TrackingWorker(repository)
    try:
        worker.configure({"mode": "foreground", "idle_threshold_seconds": 300})
        worker.tick()
        time.sleep(0.23)
        worker.tick()
        worker.tracker.flush()
        day = datetime.now().date()
        before = repository.daily_summary(day)["total"]
        worker.set_paused(True)
        time.sleep(0.30)
        worker.tick()
        worker.tracker.flush()
        paused = repository.daily_summary(day)["total"]
        assert before == paused, "暂停期间仍有计时"
        worker.set_paused(False)
        time.sleep(0.23)
        worker.tick()
        worker.tracker.flush()
        resumed = repository.daily_summary(day)["total"]
        assert before > 0 and 0.15 <= resumed - paused <= 0.45, "当前前台不可统计，或恢复错误计入暂停区间"
        worker.session_changed(False)
        time.sleep(0.23)
        worker.tick()
        worker.tracker.flush()
        unavailable = repository.daily_summary(day)["total"]
        assert unavailable == resumed, "不可用会话仍有计时"
        worker.session_changed(True)
        time.sleep(0.23)
        worker.tick()
        worker.stop()
        return {"kind": "real_windows_detector_with_temporary_sqlite", "before_seconds": before,
                "during_pause_seconds": paused, "after_resume_seconds": resumed,
                "pause_delta_seconds": paused - before, "resume_delta_seconds": resumed - paused,
                "session_unavailable_delta_seconds": unavailable - resumed,
                "user_app_identity_omitted": True, "foreground_changed_by_test": False,
                "system_lock_or_suspend_performed": False}
    finally:
        worker.stop()
        repository.close()


def verify_windows(report: dict, directory: Path) -> None:
    from ctypes import wintypes
    from PySide6.QtCore import QEventLoop
    from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget
    from daytrace.service import TrackingWorker

    application = QApplication.instance() or QApplication(["DayTrace native verification"])
    application.setQuitOnLastWindowClosed(False)
    native = _NativeApi()
    native.user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    native.user32.SetForegroundWindow.restype = wintypes.BOOL
    windows = []
    helper = None
    repository = None
    pause_repository = None

    def wait(seconds):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            application.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)
            time.sleep(0.01)

    def focus(window):
        hwnd = int(window.winId())
        for _ in range(4):
            window.show()
            window.raise_()
            window.activateWindow()
            native.user32.SetForegroundWindow(hwnd)
            wait(0.08)
            if native.foreground_window() == hwnd:
                return hwnd
        raise RuntimeError("Windows 未授予本测试窗口前台焦点；未操作其他应用")

    try:
        observed = WindowsDetector().sample()
        report["initial_native_sample"] = {
            "available": observed.available, "identified_foreground_app": observed.app is not None,
            "idle_seconds": observed.idle_seconds,
            "user_app_identity_omitted": True,
        }
        for label in ("A", "B"):
            window = QWidget()
            window.setWindowTitle("DayTrace native verification " + label)
            window.resize(350, 145)
            window.setStyleSheet("QWidget { background: #FFF3F8; color: #673E5A; font-size: 14px; }")
            layout = QVBoxLayout(window)
            layout.addWidget(QLabel("DayTrace 前台检测测试 " + label))
            layout.addWidget(QLabel("只检测本测试窗口，约 5 秒后自动关闭。"))
            windows.append(window)
        # 使用不同路径的基础 Python 创建无窗口后台进程，使归属断言有区分度。
        helper_executable = Path(sys._base_executable).with_name("pythonw.exe")
        if not helper_executable.is_file():
            raise RuntimeError("找不到独立标识的后台 Pythonw helper")
        helper = subprocess.Popen(
            [str(helper_executable), "-c", "import time; time.sleep(60)"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        helper_info = native.process_info(helper.pid, None)
        own_info = native.process_info(os.getpid(), None)
        assert helper_info and helper_info.executable and own_info and own_info.executable
        helper_app = executable_identity(helper_info.executable)
        own_app = executable_identity(own_info.executable)
        assert helper_app.key != own_app.key, "测试后台 helper 必须拥有不同应用标识"
        detector = WindowsDetector(own_pid=-1)
        repository = Repository(directory / "native.sqlite3")
        tracker = Tracker(repository, flush_interval=0.5)
        samples = []
        sample_date = None
        foreground_handles = set()
        for index in range(8):
            hwnd = focus(windows[index % 2])
            foreground_handles.add(hwnd)
            sample = detector.sample()
            assert sample.available and sample.app and sample.app.key == own_app.key, "本测试窗口归属识别失败"
            sample_date = sample.wall.date()
            samples.append(sample.monotonic)
            tracker.observe(sample)
            wait(0.23)
        tracker.flush()
        summary = repository.daily_summary(sample_date)
        keys = [app["key"] for app in summary["apps"]]
        span = samples[-1] - samples[0]
        assert len(foreground_handles) == 2 and keys == [own_app.key]
        assert helper.poll() is None and helper_app.key not in keys, "后台 helper 被错误计入"
        assert abs(summary["total"] - span) < 0.02, "多个窗口导致重复计时"
        report["native_two_windows"] = {
            "own_test_windows": len(foreground_handles), "samples": len(samples),
            "distinct_saved_apps": len(keys), "observed_span_seconds": span,
            "saved_seconds": summary["total"], "background_helper_alive_during_test": True,
            "background_helper_saved": False, "double_counted": False,
        }
        # 真实 detector 接入服务；仅使用服务暂停 API，不改变系统锁屏状态。
        pause_repository = Repository(directory / "pause.sqlite3")
        worker = TrackingWorker(pause_repository)
        worker.detector = detector
        worker.configure({"mode": "foreground", "idle_threshold_seconds": 300})
        focus(windows[0])
        worker.tick()
        wait(0.23)
        worker.tick()
        worker.tracker.flush()
        day = datetime.now().date()
        before = pause_repository.daily_summary(day)["total"]
        worker.set_paused(True)
        wait(0.30)
        worker.tick()
        worker.tracker.flush()
        paused = pause_repository.daily_summary(day)["total"]
        assert before == paused, "暂停期间仍有计时"
        worker.set_paused(False)
        wait(0.23)
        worker.tick()
        worker.tracker.flush()
        resumed = pause_repository.daily_summary(day)["total"]
        assert 0.15 <= resumed - paused <= 0.40, "恢复时累计了暂停区间"
        worker.session_changed(False)
        wait(0.23)
        worker.tick()
        worker.tracker.flush()
        session_paused = pause_repository.daily_summary(day)["total"]
        assert session_paused == resumed, "会话不可用期间仍有计时"
        worker.session_changed(True)
        wait(0.23)
        worker.tick()
        worker.stop()
        report["real_detector_service_pause"] = {
            "before_seconds": before, "during_pause_seconds": paused,
            "after_resume_seconds": resumed, "paused_delta_seconds": paused - before,
            "resume_delta_seconds": resumed - paused,
            "session_unavailable_delta_seconds": session_paused - resumed,
            "system_lock_or_suspend_performed": False,
        }
    finally:
        if helper is not None:
            if helper.poll() is None:
                helper.terminate()
                helper.wait(timeout=10)
            report["background_helper_stopped"] = helper.poll() is not None
        if repository is not None:
            repository.close()
        if pause_repository is not None:
            pause_repository.close()
        for window in windows:
            window.close()
            window.deleteLater()
        application.processEvents()
        report["test_windows_closed"] = len(windows)


def main() -> int:
    parser = argparse.ArgumentParser(description="DayTrace Windows 原生验证")
    parser.add_argument("--report", type=Path, default=PROJECT / "qa-output" / "native-report.json")
    args = parser.parse_args()
    report = {"generated_at": datetime.now().astimezone().isoformat(), "platform": sys.platform,
              "python": sys.version.split()[0], "production_database_used": False,
              "captured_titles_urls_input_screenshots": False, "outcome": "running"}
    temporary_path = None
    try:
        report["unit_tests"] = run_unit_tests()
        if report["unit_tests"]["returncode"]:
            raise RuntimeError("WindowsDetector 自动化测试未通过")
        if sys.platform != "win32":
            raise RuntimeError("原生窗口测试仅支持 Windows")
        with tempfile.TemporaryDirectory(prefix="daytrace-native-") as temp:
            temporary = Path(temp)
            temporary_path = temporary
            report["gap_protection"] = verify_gap(temporary / "gap.sqlite3")
            report["native_session_messages"] = verify_native_messages()
            report["live_service_pause"] = verify_live_service_pause(temporary / "live-pause.sqlite3")
            verify_windows(report, temporary)
        report["temporary_databases_removed"] = True
        report["outcome"] = "passed"
    except Exception as error:
        report["outcome"] = "failed_or_blocked"
        report["error"] = str(error)
    if temporary_path is not None:
        report["temporary_databases_removed"] = not temporary_path.exists()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"outcome": report["outcome"], "report": str(args.report)}, ensure_ascii=True))
    return 0 if report["outcome"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
