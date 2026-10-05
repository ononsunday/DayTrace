"""只传入内存中的 MSG；测试不会向系统发送锁屏、休眠或会话消息。"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import ctypes
from ctypes import wintypes
import sys
import sqlite3
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone

import pytest
from PySide6.QtCore import QMetaObject, QThread, Qt
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from daytrace.app import Commands, DayTraceApplication, NativeEvents
import daytrace.app as app_module
import daytrace.service as service_module
from daytrace.core.models import AppIdentity, Observation
from daytrace.core.repository import Repository
from daytrace.ui.main_window import MainWindow


pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows MSG 类型验证")


@pytest.fixture(scope="session")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def native_events(qt_app):
    commands = Commands()
    received = []
    commands.session.connect(received.append)
    events = NativeEvents(commands)
    yield events, received
    commands.deleteLater()
    qt_app.processEvents()


def send(events, message, parameter):
    msg = wintypes.MSG()
    msg.message, msg.wParam = message, parameter
    assert events.nativeEventFilter(b"windows_generic_MSG", ctypes.addressof(msg)) == (False, 0)


def test_rdp_reconnect_and_unlock_do_not_cancel_outstanding_suspend(native_events):
    events, received = native_events
    send(events, 0x02B1, 4)  # WTS_REMOTE_DISCONNECT
    send(events, 0x02B1, 7)  # WTS_SESSION_LOCK
    send(events, 0x02B1, 3)  # WTS_REMOTE_CONNECT，仍然锁定
    send(events, 0x0218, 4)  # PBT_APMSUSPEND
    send(events, 0x02B1, 8)  # WTS_SESSION_UNLOCK，仍然休眠
    send(events, 0x0218, 6)  # PBT_APMRESUMECRITICAL
    assert received == [False, False, False, False, False, True]
    assert not events.locked and not events.disconnected and not events.suspended


def test_console_disconnect_and_logoff_each_require_matching_recovery(native_events):
    events, received = native_events
    send(events, 0x02B1, 2)  # WTS_CONSOLE_DISCONNECT
    send(events, 0x02B1, 6)  # WTS_SESSION_LOGOFF
    send(events, 0x02B1, 1)  # WTS_CONSOLE_CONNECT，不解除 logoff
    send(events, 0x02B1, 5)  # WTS_SESSION_LOGON
    assert received == [False, False, False, True]


@pytest.mark.parametrize("resume", [7, 18])
def test_normal_and_automatic_resume_restore_session(native_events, resume):
    events, received = native_events
    send(events, 0x0218, 4)
    send(events, 0x0218, resume)
    assert received == [False, True]


def test_unrelated_native_messages_are_forwarded_without_state_changes(native_events):
    events, received = native_events
    send(events, 0x001E, 0)  # WM_TIMECHANGE 由采样的墙钟/单调时钟差防护。
    send(events, 0x02B1, 10)  # 未处理的 session-create 通知
    assert received == []
    assert not events.locked and not events.disconnected and not events.suspended


@pytest.mark.parametrize("operation", ["delete_date", "clear_history", "export", "backup", "restore"])
def test_failed_save_barrier_blocks_all_data_operations(qt_app, monkeypatch, tmp_path, operation):
    called, barriers = [], []
    def blocked():
        barriers.append(True)
        return False
    def record(name):
        return lambda *args, **kwargs: called.append(name)
    controller = SimpleNamespace(
        save_barrier=blocked,
        repository=SimpleNamespace(**{name: record(name) for name in (
            "delete_date", "clear_history", "export", "backup", "restore",
        )}),
        window=SimpleNamespace(invalidate_diary=record("invalidate"), refresh=record("refresh")),
        report_error=record("unexpected-error"),
    )
    # 文件对话框只返回测试路径，测试不打开原生对话框，也不创建文件。
    path = str(tmp_path / "not-written.sqlite3")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: (path, ""))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args, **kwargs: (path, ""))
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, "information", record("unexpected-success"))
    arguments = ("2026-10-03",) if operation == "delete_date" else ("json",) if operation == "export" else ()
    getattr(DayTraceApplication, operation)(controller, *arguments)
    assert barriers == [True]
    assert called == [] and not (tmp_path / "not-written.sqlite3").exists()


@pytest.fixture
def settings_controller(qt_app, tmp_path, monkeypatch):
    class StaticDetector:
        def sample(self):
            return Observation(0, datetime(2026, 10, 3, tzinfo=timezone.utc), None)
    monkeypatch.setattr(service_module, "WindowsDetector", StaticDetector)
    repository = Repository(tmp_path / "settings.sqlite3")
    worker = service_module.TrackingWorker(repository)
    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.start)
    thread.finished.connect(worker.deleteLater)
    controller = SimpleNamespace(repository=repository, worker=worker, thread=thread)
    controller.save_barrier = lambda: DayTraceApplication.save_barrier(controller)
    actions = {"settings_changed": lambda options: DayTraceApplication.settings_changed(controller, options)}
    window = MainWindow(repository, actions)
    window.allow_close = True
    controller.window = window
    window.show_page(5)
    thread.start()
    yield controller, window.pages[5]
    if thread.isRunning():
        QMetaObject.invokeMethod(worker, "stop", Qt.ConnectionType.BlockingQueuedConnection)
        thread.quit()
        assert thread.wait(3000)
    window.close()
    window.deleteLater()
    qt_app.processEvents()
    repository.close()


def test_root_settings_apply_in_real_qthread_before_ui_success_and_persist_theme(settings_controller, monkeypatch):
    controller, page = settings_controller
    monkeypatch.setattr(app_module, "set_autostart", lambda *args: pytest.fail("未改变自启动时不应写注册表"))
    page.mode.setCurrentIndex(page.mode.findData("active"))
    page.idle.setValue(8)
    page.poll.setCurrentIndex(page.poll.findData(1))
    page.theme_choice.setCurrentIndex(page.theme_choice.findData("dark"))
    page.save()
    assert page.saved.text() == "设置已保存并生效。"
    assert controller.worker.tracker.mode == "active"
    assert controller.worker.tracker.idle_threshold == 480 and controller.worker.timer.interval() == 1000
    assert controller.repository.get_setting("mode") == "active"
    assert controller.repository.get_setting("theme") == "dark" and controller.window.theme == "dark"


def test_explicit_autostart_failure_raises_and_ui_does_not_commit_or_report_success(settings_controller, monkeypatch):
    controller, page = settings_controller
    calls = []
    def registry_failure(enabled):
        calls.append(enabled)
        raise OSError("simulated registry write failure")
    monkeypatch.setattr(app_module, "set_autostart", registry_failure)
    with pytest.raises(RuntimeError, match="开机启动设置失败"):
        DayTraceApplication.settings_changed(controller, {"autostart": True, "mode": "active", "theme": "dark"})
    page.autostart.setChecked(True)
    page.mode.setCurrentIndex(page.mode.findData("active"))
    page.theme_choice.setCurrentIndex(page.theme_choice.findData("dark"))
    page.save()
    assert calls == [True, True]
    assert page.saved.text().startswith("保存失败：") and "已保存并生效" not in page.saved.text()
    assert controller.repository.get_setting("autostart", False) is False
    assert controller.repository.get_setting("mode", "foreground") == "foreground"
    assert controller.worker.tracker.mode == "foreground" and controller.window.theme == "light"


def test_root_quit_retains_thread_and_database_on_save_failure_then_retries_safely(settings_controller, monkeypatch):
    controller, page = settings_controller
    calls = []
    controller.quitting = False
    controller.wts = None
    controller.reminder = SimpleNamespace(stop=lambda: calls.append("reminder-stop"), start=lambda: calls.append("reminder-start"))
    controller.tray = SimpleNamespace(hide=lambda: calls.append("tray-hide"))
    controller.application = SimpleNamespace(quit=lambda: calls.append("application-quit"))
    controller.show = lambda: calls.append("show")
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: calls.append("warning"))
    app = AppIdentity("exit-test", "退出保存测试")
    wall = datetime(2026, 10, 3, 9, tzinfo=timezone.utc)
    # 先同步设置，确保工作线程启动已经完成，再注入一个已确认的两秒批次。
    page.save()
    for elapsed in (1, 3):
        controller.worker.tracker.observe(Observation(elapsed, wall + timedelta(seconds=elapsed), app))
    original_append = controller.repository.append_segments
    def disk_failure(segments):
        raise OSError("simulated exit write failure")
    monkeypatch.setattr(controller.repository, "append_segments", disk_failure)
    DayTraceApplication.quit(controller)
    assert controller.quitting is False and controller.thread.isRunning() and controller.worker.paused
    assert controller.repository.daily_summary("2026-10-03")["total"] == 0
    assert calls == ["reminder-stop", "reminder-start", "show", "warning"]
    monkeypatch.setattr(controller.repository, "append_segments", original_append)
    DayTraceApplication.quit(controller)
    assert controller.quitting and not controller.thread.isRunning()
    assert calls[-3:] == ["reminder-stop", "tray-hide", "application-quit"]
    with pytest.raises(sqlite3.ProgrammingError):
        controller.repository.daily_summary("2026-10-03")
    reopened = Repository(controller.repository.path)
    try:
        assert reopened.daily_summary("2026-10-03")["total"] == 2
    finally:
        reopened.close()
