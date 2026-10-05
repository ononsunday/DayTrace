"""用可控检测器和真实 SQLite 验证常驻服务的保存边界。"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime, timedelta, timezone

import pytest
from PySide6.QtCore import QMetaObject, QThread, Qt, Q_RETURN_ARG
from PySide6.QtWidgets import QApplication

from daytrace.core.models import AppIdentity, Observation
from daytrace.core.repository import Repository
import daytrace.service as service


APP_A = AppIdentity("test-code.exe", "测试编辑器")
APP_B = AppIdentity("test-browser.exe", "测试浏览器")
DAY = "2026-10-03"


class ControlledDetector:
    def __init__(self):
        self.calls = 0
        self.set(0)

    def set(self, seconds, app=APP_A, idle=0, available=True):
        self.observation = Observation(
            seconds, datetime(2026, 10, 3, 9, tzinfo=timezone.utc) + timedelta(seconds=seconds),
            app, idle, available,
        )

    def sample(self):
        self.calls += 1
        return self.observation


@pytest.fixture(scope="session")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def worker(qt_app, tmp_path, monkeypatch):
    detector = ControlledDetector()
    monkeypatch.setattr(service, "WindowsDetector", lambda: detector)
    repository = Repository(tmp_path / "service.sqlite3")
    instance = service.TrackingWorker(repository)
    instance.configure({"mode": "foreground", "idle_threshold_seconds": 300})
    yield instance, detector, repository
    instance.stop()
    instance.deleteLater()
    qt_app.processEvents()
    repository.close()


def total(repository):
    return repository.daily_summary(DAY)["total"]


def test_pause_flushes_confirmed_time_and_resume_starts_new_boundary(worker):
    instance, detector, repository = worker
    states = []
    instance.status.connect(lambda label, paused: states.append((label, paused)))
    instance.tick()
    detector.set(2)
    instance.tick()
    assert total(repository) == 0  # 两秒待批量保存，没有逐秒写库。
    instance.set_paused(True)
    assert total(repository) == 2
    detector.set(100)
    instance.tick()
    assert detector.calls == 2 and total(repository) == 2
    instance.set_paused(False)
    detector.set(102)
    instance.tick()
    instance.stop()
    assert total(repository) == 4
    assert any(paused for _, paused in states) and states[-1][1] is False


def test_session_events_flush_and_preserve_user_pause(worker):
    instance, detector, repository = worker
    instance.tick()
    detector.set(2)
    instance.tick()
    instance.session_changed(False)
    assert total(repository) == 2
    detector.set(100)
    instance.tick()
    assert detector.calls == 2
    instance.set_paused(True)
    instance.session_changed(True)
    assert instance.paused and detector.calls == 2
    instance.set_paused(False)
    detector.set(102)
    instance.tick()
    instance.stop()
    assert total(repository) == 4


def test_mode_configuration_commits_old_mode_and_does_not_bridge_gap(worker):
    instance, detector, repository = worker
    instance.tick()
    detector.set(2)
    instance.tick()
    instance.configure({"mode": "active", "idle_threshold_seconds": 60})
    assert total(repository) == 2
    detector.set(100, idle=59)
    instance.tick()
    detector.set(102, idle=61)
    instance.tick()
    instance.stop()
    timeline = repository.daily_summary(DAY)["timeline"]
    assert [(row["mode"], row["seconds"]) for row in timeline] == [("foreground", 2), ("active", 1)]


def test_start_uses_saved_options_and_timer_stops_on_exit(worker):
    instance, detector, repository = worker
    repository.set_setting("mode", "active")
    repository.set_setting("idle_threshold_seconds", 75)
    repository.set_setting("poll_interval_seconds", 1)
    instance.start()
    assert instance.timer.isActive() and instance.timer.interval() == 1000
    assert instance.tracker.mode == "active" and instance.tracker.idle_threshold == 75
    assert detector.calls == 1
    instance.configure({"poll_interval_seconds": 2})
    assert instance.timer.interval() == 2000
    instance.stop()
    assert not instance.timer.isActive()


def test_stop_commits_pending_records_readable_from_another_connection(worker):
    instance, detector, repository = worker
    stopped = []
    instance.stopped.connect(lambda: stopped.append(True))
    instance.tick()
    detector.set(2)
    instance.tick()
    assert total(repository) == 0
    instance.stop()
    reopened = Repository(repository.path)
    try:
        assert total(reopened) == 2 and stopped == [True]
    finally:
        reopened.close()


def test_database_write_error_keeps_pending_batch_and_retry_does_not_duplicate(worker, monkeypatch):
    instance, detector, repository = worker
    original_append = repository.append_segments
    attempts = []
    statuses = []
    instance.status.connect(lambda label, paused: statuses.append(label))

    def fail_once(segments):
        attempts.append(True)
        if len(attempts) == 1:
            raise OSError("simulated disk write error")
        original_append(segments)

    monkeypatch.setattr(repository, "append_segments", fail_once)
    instance.tick()
    detector.set(2)
    instance.tick()
    detector.set(4, APP_B)
    instance.tick()  # 切换时写入失败，服务继续工作并保留批次。
    assert total(repository) == 0 and any("失败" in label for label in statuses)
    detector.set(6, APP_B)
    instance.tick()
    instance.stop()
    summary = repository.daily_summary(DAY)
    assert summary["total"] == 6
    assert {row["app_key"]: row["seconds"] for row in summary["timeline"]} == {APP_A.key: 4, APP_B.key: 2}
    assert len(attempts) == 2


@pytest.mark.parametrize("transition", ["pause", "session"])
def test_pause_and_session_boundary_stop_counting_even_when_saving_fails(worker, monkeypatch, transition):
    instance, detector, repository = worker
    instance.tick()
    detector.set(2)
    instance.tick()
    original_append = repository.append_segments

    def unavailable_disk(segments):
        raise OSError("simulated disk unavailable across pause and resume")

    monkeypatch.setattr(repository, "append_segments", unavailable_disk)
    if transition == "pause":
        instance.set_paused(True)
        assert instance.paused
    else:
        instance.session_changed(False)
        assert not instance.session_available
    detector.set(3)
    instance.tick()
    assert detector.calls == 2 and total(repository) == 0
    # 暂停区间只有两秒，低于 max_gap，必须靠正确切断边界避免误记。
    detector.set(4)
    if transition == "pause":
        instance.set_paused(False)
    else:
        instance.session_changed(True)
    detector.set(6)
    instance.tick()
    monkeypatch.setattr(repository, "append_segments", original_append)
    instance.stop()
    summary = repository.daily_summary(DAY)
    assert summary["total"] == 4  # [0,2] 与 [4,6]，中间的锁屏/暂停不计。
    assert [(row["start"][11:19], row["end"][11:19]) for row in summary["timeline"]] == [
        ("09:00:00", "09:00:02"), ("09:00:04", "09:00:06"),
    ]


def test_barrier_returns_real_bool_across_qthread_and_failed_batch_can_be_retried(qt_app, tmp_path, monkeypatch):
    repository = Repository(tmp_path / "barrier.sqlite3")
    instance = service.TrackingWorker(repository)
    detector = ControlledDetector()
    instance.detector = detector
    instance.tick()
    detector.set(2)
    instance.tick()
    original_append = repository.append_segments

    def unavailable_disk(segments):
        raise OSError("simulated write failure")

    monkeypatch.setattr(repository, "append_segments", unavailable_disk)
    thread = QThread()
    instance.moveToThread(thread)
    thread.finished.connect(instance.deleteLater)
    thread.start()
    try:
        failed = QMetaObject.invokeMethod(instance, "barrier", Qt.ConnectionType.BlockingQueuedConnection, Q_RETURN_ARG(bool))
        assert type(failed) is bool and failed is False and total(repository) == 0
        monkeypatch.setattr(repository, "append_segments", original_append)
        saved = QMetaObject.invokeMethod(instance, "barrier", Qt.ConnectionType.BlockingQueuedConnection, Q_RETURN_ARG(bool))
        assert type(saved) is bool and saved is True and total(repository) == 2
    finally:
        QMetaObject.invokeMethod(instance, "stop", Qt.ConnectionType.BlockingQueuedConnection)
        thread.quit()
        assert thread.wait(3000)
        repository.close()


def test_failed_stop_keeps_batch_pauses_timer_and_successful_retry_saves_it(worker, monkeypatch):
    instance, detector, repository = worker
    stopped = []
    instance.stopped.connect(lambda: stopped.append(True))
    instance.start()
    detector.set(2)
    instance.tick()
    original_append = repository.append_segments
    def disk_failure(segments):
        raise OSError("simulated disk failure during exit")
    monkeypatch.setattr(repository, "append_segments", disk_failure)
    assert instance.stop() is False
    assert instance.paused and instance.timer.isActive() and total(repository) == 0
    detector.set(4)
    instance.tick()
    assert detector.calls == 2 and stopped == []
    monkeypatch.setattr(repository, "append_segments", original_append)
    assert instance.stop() is True
    assert total(repository) == 2 and stopped == [True] and not instance.timer.isActive()
