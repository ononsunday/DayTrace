from datetime import datetime, timedelta
import sqlite3

import pytest

from daytrace.core.models import AppIdentity, Observation, Segment
from daytrace.core.repository import Repository
from daytrace.core.tracker import Tracker


A = AppIdentity("code.exe", "VS Code")
B = AppIdentity("chrome.exe", "Chrome")
BASE = datetime(2026, 10, 2, 14)


@pytest.fixture
def repository(tmp_path):
    repo = Repository(tmp_path / "history.sqlite3")
    yield repo
    repo.close()


def obs(seconds, app=A, idle=0, available=True, wall=None):
    return Observation(float(seconds), wall or BASE + timedelta(seconds=seconds), app, idle, available)


def test_only_one_foreground_app_and_no_duplicate_windows(repository):
    tracker = Tracker(repository)
    tracker.observe(obs(0))
    tracker.observe(obs(2))
    tracker.observe(obs(4, B))
    tracker.observe(obs(6, B))
    tracker.flush()
    summary = repository.daily_summary(BASE.date())
    assert summary["total"] == 6
    assert {app["key"]: app["seconds"] for app in summary["apps"]} == {A.key: 4, B.key: 2}
    assert len(summary["timeline"]) == 2


def test_foreground_mode_counts_reading_without_input(repository):
    tracker = Tracker(repository)
    for seconds in range(0, 20, 2):
        tracker.observe(obs(seconds, idle=1000 + seconds))
    tracker.flush()
    assert repository.daily_summary(BASE.date())["total"] == 18


def test_active_exact_threshold_and_conservative_resume(repository):
    tracker = Tracker(repository, mode="active", idle_threshold=5)
    tracker.observe(obs(0, idle=3))
    tracker.observe(obs(4, idle=7))
    tracker.observe(obs(6, idle=9))
    tracker.observe(obs(8, idle=0.5))
    tracker.observe(obs(10, idle=2.5))
    tracker.flush()
    summary = repository.daily_summary(BASE.date())
    assert summary["total"] == pytest.approx(4.5)
    assert [row["seconds"] for row in summary["timeline"]] == [2, 2.5]


def test_active_idle_and_resume_within_single_poll(repository):
    tracker = Tracker(repository, mode="active", idle_threshold=5)
    tracker.observe(obs(0, idle=4))
    tracker.observe(obs(4, idle=1))
    tracker.flush()
    summary = repository.daily_summary(BASE.date())
    assert summary["total"] == 2
    assert [row["seconds"] for row in summary["timeline"]] == [1, 1]


def test_active_unknown_idle_is_not_counted(repository):
    tracker = Tracker(repository, mode="active")
    tracker.observe(obs(0, idle=None))
    tracker.observe(obs(2, idle=0))
    tracker.flush()
    assert repository.daily_summary(BASE.date())["total"] == 0


@pytest.mark.parametrize("before,after", [(float("nan"), 0), (0, float("nan")), (1000, 1100), (0, float("inf"))])
def test_active_invalid_or_inconsistent_idle_is_not_counted(repository, before, after):
    tracker = Tracker(repository, mode="active")
    tracker.observe(obs(0, idle=before))
    tracker.observe(obs(2, idle=after))
    tracker.flush()
    assert repository.daily_summary(BASE.date())["total"] == 0


def test_lock_sleep_and_pause_leave_unobserved_gaps(repository):
    tracker = Tracker(repository)
    tracker.observe(obs(0))
    tracker.observe(obs(2))
    tracker.observe(obs(4, available=False))
    tracker.observe(obs(20, available=False))
    tracker.observe(obs(22))
    tracker.observe(obs(24))
    tracker.reset()
    tracker.observe(obs(60))
    tracker.observe(obs(62))
    tracker.flush()
    summary = repository.daily_summary(BASE.date())
    assert summary["total"] == 6
    assert len(summary["timeline"]) == 3


def test_long_gap_and_wall_clock_changes_are_discarded(repository):
    tracker = Tracker(repository)
    tracker.observe(obs(0))
    tracker.observe(obs(300))
    tracker.observe(obs(302))
    tracker.observe(obs(304, wall=BASE + timedelta(seconds=604)))
    tracker.observe(obs(306, wall=BASE + timedelta(seconds=606)))
    tracker.flush()
    assert repository.daily_summary(BASE.date())["total"] == 4


def test_clock_rollback_repeated_timestamps_do_not_hide_new_valid_usage(repository):
    tracker = Tracker(repository, flush_interval=2)
    tracker.observe(obs(0))
    tracker.observe(obs(2))
    tracker.observe(obs(4, wall=BASE))
    tracker.observe(obs(6, wall=BASE + timedelta(seconds=2)))
    tracker.flush()
    assert repository.daily_summary(BASE.date())["total"] == 4


def test_active_minor_wall_clock_drift_maps_both_valid_pieces(repository):
    tracker = Tracker(repository, mode="active", idle_threshold=300)
    tracker.observe(obs(0, idle=299.8))
    tracker.observe(obs(2, idle=1, wall=BASE + timedelta(seconds=1.6)))
    tracker.flush()
    timeline = repository.daily_summary(BASE.date())["timeline"]
    assert [row["seconds"] for row in timeline] == pytest.approx([0.2, 1])
    assert datetime.fromisoformat(timeline[0]["end"]) == BASE + timedelta(seconds=0.16)
    assert datetime.fromisoformat(timeline[1]["start"]) == BASE + timedelta(seconds=0.8)
    assert datetime.fromisoformat(timeline[1]["end"]) == BASE + timedelta(seconds=1.6)


def test_active_minor_drift_preserves_short_resumed_tail(repository):
    tracker = Tracker(repository, mode="active", idle_threshold=300)
    tracker.observe(obs(0, idle=302))
    tracker.observe(obs(2, idle=0.2, wall=BASE + timedelta(seconds=1.6)))
    tracker.flush()
    timeline = repository.daily_summary(BASE.date())["timeline"]
    assert len(timeline) == 1
    assert timeline[0]["seconds"] == pytest.approx(0.2)
    assert datetime.fromisoformat(timeline[0]["start"]) == BASE + timedelta(seconds=1.44)


def test_backward_wall_interval_is_never_counted_even_for_short_monotonic_poll(repository):
    tracker = Tracker(repository, mode="active", idle_threshold=5)
    tracker.observe(obs(0, idle=4.9))
    tracker.observe(obs(0.2, idle=0.01, wall=BASE - timedelta(seconds=0.2)))
    tracker.flush()
    assert repository.daily_summary(BASE.date())["total"] == 0


def test_duplicate_or_out_of_order_poll_does_not_change_baseline(repository):
    tracker = Tracker(repository)
    tracker.observe(obs(0))
    tracker.observe(obs(2))
    tracker.observe(obs(2, B))
    tracker.observe(obs(1, B))
    tracker.observe(obs(4))
    tracker.flush()
    assert repository.daily_summary(BASE.date())["total"] == 4
    assert len(repository.daily_summary(BASE.date())["apps"]) == 1


def test_midnight_split_and_periodic_writes_merge(repository):
    tracker = Tracker(repository, flush_interval=2)
    wall = datetime(2026, 10, 2, 23, 59, 58)
    for seconds in (0, 2, 4, 6):
        tracker.observe(obs(seconds, wall=wall + timedelta(seconds=seconds)))
    assert repository.daily_summary("2026-10-02")["total"] == 2
    summary = repository.daily_summary("2026-10-03")
    assert summary["total"] == 4
    assert len(summary["timeline"]) == 1


def test_exclusion_applies_to_future_intervals(repository):
    tracker = Tracker(repository)
    tracker.observe(obs(0))
    tracker.observe(obs(2))
    tracker.flush()
    repository.update_app(A.key, excluded=True)
    tracker.observe(obs(4))
    tracker.observe(obs(6))
    tracker.flush()
    assert repository.daily_summary(BASE.date())["total"] == 2


def test_configure_flushes_confirmed_time_and_resets_tail(repository):
    tracker = Tracker(repository)
    tracker.observe(obs(0))
    tracker.observe(obs(2))
    tracker.configure("active", 5)
    tracker.observe(obs(10, idle=0))
    tracker.observe(obs(12, idle=2))
    tracker.flush()
    summary = repository.daily_summary(BASE.date())
    assert summary["total"] == 4
    assert [row["mode"] for row in summary["timeline"]] == ["foreground", "active"]


def test_database_error_retains_batch_for_retry_without_double_count(repository, monkeypatch):
    tracker = Tracker(repository)
    tracker.observe(obs(0))
    tracker.observe(obs(2))
    append = repository.append_segments
    monkeypatch.setattr(repository, "append_segments", lambda segments: (_ for _ in ()).throw(sqlite3.OperationalError("disk full")))
    with pytest.raises(sqlite3.OperationalError):
        tracker.flush()
    tracker.observe(obs(4))
    monkeypatch.setattr(repository, "append_segments", append)
    tracker.flush()
    tracker.flush()
    assert repository.daily_summary(BASE.date())["total"] == 4


def test_error_after_successful_commit_can_be_retried(repository, monkeypatch):
    tracker = Tracker(repository)
    tracker.observe(obs(0))
    tracker.observe(obs(2))
    append = repository.append_segments

    def ambiguous_success(segments):
        append(segments)
        raise RuntimeError("caller interrupted after commit")

    monkeypatch.setattr(repository, "append_segments", ambiguous_success)
    with pytest.raises(RuntimeError):
        tracker.flush()
    tracker.observe(obs(4))
    monkeypatch.setattr(repository, "append_segments", append)
    tracker.flush()
    assert repository.daily_summary(BASE.date())["total"] == 4


def test_invalid_configuration_is_rejected(repository):
    with pytest.raises(ValueError):
        Tracker(repository, mode="background")
    with pytest.raises(ValueError):
        Tracker(repository, idle_threshold=0)
    with pytest.raises(ValueError):
        Tracker(repository, max_gap=float("nan"))
    with pytest.raises(ValueError):
        Tracker(repository, flush_interval=0)


def test_repeated_database_errors_never_grow_pending_beyond_bound(repository, monkeypatch):
    tracker = Tracker(repository)
    tracker._pending = [Segment(A, BASE + timedelta(seconds=i * 2), BASE + timedelta(seconds=i * 2 + 1), 1) for i in range(4096)]
    tracker._frozen_count = 4096
    monkeypatch.setattr(repository, "append_segments", lambda segments: (_ for _ in ()).throw(sqlite3.OperationalError("disk full")))
    for _ in range(10):
        with pytest.raises(sqlite3.OperationalError):
            tracker._queue(Segment(B, BASE, BASE + timedelta(seconds=1), 1))
    assert len(tracker._pending) == 4096


def test_reset_database_error_still_detaches_observation(repository, monkeypatch):
    tracker = Tracker(repository)
    tracker.observe(obs(0))
    tracker.observe(obs(2))
    append = repository.append_segments
    monkeypatch.setattr(repository, "append_segments", lambda segments: (_ for _ in ()).throw(sqlite3.OperationalError("disk full")))
    with pytest.raises(sqlite3.OperationalError):
        tracker.reset()
    monkeypatch.setattr(repository, "append_segments", append)
    tracker.observe(obs(4))
    tracker.observe(obs(6))
    tracker.flush()
    assert repository.daily_summary(BASE.date())["total"] == 4


def test_short_lock_reset_error_never_backfills_locked_interval(repository, monkeypatch):
    tracker = Tracker(repository, max_gap=6)
    tracker.observe(obs(0))
    tracker.observe(obs(2))
    append = repository.append_segments
    monkeypatch.setattr(repository, "append_segments", lambda segments: (_ for _ in ()).throw(sqlite3.OperationalError("disk full")))
    with pytest.raises(sqlite3.OperationalError):
        tracker.reset()  # 锁屏事件先切断，保存失败后的旧区间仍保留待重试。
    assert tracker._previous is None
    assert tracker._last_flush is None
    assert tracker.status == "等待检测"
    assert len(tracker._pending) == tracker._frozen_count == 1
    monkeypatch.setattr(repository, "append_segments", append)
    tracker.observe(obs(4))  # 两秒后解锁，仍短于 max_gap，必须重新建立基准。
    tracker.flush()
    assert repository.daily_summary(BASE.date())["total"] == 2
    tracker.observe(obs(6))
    tracker.flush()
    summary = repository.daily_summary(BASE.date())
    assert summary["total"] == 4
    assert len(summary["timeline"]) == 2


def test_configuration_applies_new_mode_after_flush_error_without_changing_old_batch(repository, monkeypatch):
    tracker = Tracker(repository)
    tracker.observe(obs(0))
    tracker.observe(obs(2))
    append = repository.append_segments
    monkeypatch.setattr(repository, "append_segments", lambda segments: (_ for _ in ()).throw(sqlite3.OperationalError("disk full")))
    with pytest.raises(sqlite3.OperationalError):
        tracker.configure("active", 5)
    assert tracker.mode == "active"
    assert tracker.idle_threshold == 5
    assert tracker._pending[0].mode == "foreground"
    assert tracker._previous is None
    monkeypatch.setattr(repository, "append_segments", append)
    tracker.observe(obs(4, idle=10))
    tracker.observe(obs(6, idle=12))
    tracker.flush()
    summary = repository.daily_summary(BASE.date())
    assert summary["total"] == 2
    assert summary["timeline"][0]["mode"] == "foreground"
