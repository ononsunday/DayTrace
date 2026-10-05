from datetime import date, datetime, timedelta
import csv
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from daytrace.core.models import AppIdentity, Segment
from daytrace.core.repository import Repository


A = AppIdentity("code.exe", "VS Code", r"C:\Apps\Code.exe")
B = AppIdentity("chrome.exe", "Chrome")
BASE = datetime(2026, 10, 2, 14)


@pytest.fixture
def repository(tmp_path):
    repo = Repository(tmp_path / "history.sqlite3")
    yield repo
    repo.close()


def segment(offset=0, seconds=2, app=A):
    return Segment(app, BASE + timedelta(seconds=offset), BASE + timedelta(seconds=offset + seconds), seconds)


def test_persistence_idempotent_ingestion_and_contiguous_merge(repository):
    repository.append_segments([segment()])
    repository.append_segments([segment()])
    repository.append_segments([segment(2)])
    summary = repository.daily_summary(date(2026, 10, 2))
    assert summary["total"] == 4
    assert len(summary["timeline"]) == 1
    second = Repository(repository.path)
    assert second.daily_summary("2026-10-02")["total"] == 4
    second.close()


def test_unknown_apps_and_category_edit(repository):
    repository.append_segments([segment()])
    assert repository.list_apps()[0]["category"] == "学习与编程"
    repository.update_app(A.key, name="编程工具", category="工作办公", icon="icon.png")
    repository.append_segments([segment(2)])
    summary = repository.daily_summary(BASE.date())
    assert summary["apps"][0]["name"] == "编程工具"
    assert summary["categories"] == [{"category": "工作办公", "seconds": 4}]
    assert summary["apps"][0]["icon"] == "icon.png"
    assert summary["apps"][0]["executable"] == A.executable
    assert summary["timeline"][0]["executable"] == A.executable


def test_excluded_apps_do_not_generate_history(repository):
    repository.update_app(A.key, excluded=True)
    repository.append_segments([segment()])
    assert repository.daily_summary(BASE.date())["total"] == 0
    repository.update_app(A.key, excluded=False)
    repository.append_segments([segment(4)])
    assert repository.daily_summary(BASE.date())["total"] == 2


def test_midnight_repository_boundary_and_empty_trend_days(repository):
    start = datetime(2026, 10, 2, 23, 59, 59)
    repository.append_segments([Segment(A, start, start + timedelta(seconds=4), 4)])
    assert repository.daily_summary("2026-10-02")["total"] == 1
    assert repository.daily_summary("2026-10-03")["total"] == 3
    assert repository.trend("2026-10-03", 3) == [
        {"date": "2026-10-01", "seconds": 0},
        {"date": "2026-10-02", "seconds": 1},
        {"date": "2026-10-03", "seconds": 3},
    ]


def test_midnight_retry_preserves_ingestion_identity(repository):
    start = datetime(2026, 10, 2, 23, 59, 59)
    item = Segment(A, start, start + timedelta(seconds=4), 4, "foreground", "same-event")
    repository.append_segments([item])
    repository.append_segments([item])
    assert repository.daily_summary("2026-10-02")["total"] == 1
    assert repository.daily_summary("2026-10-03")["total"] == 3
    new_event = Segment(A, item.start, item.end, item.seconds, item.mode, "different-event")
    repository.append_segments([new_event])
    assert repository.daily_summary("2026-10-02")["total"] == 2
    assert repository.daily_summary("2026-10-03")["total"] == 6


def test_diary_does_not_increase_computer_usage(repository):
    repository.save_diary(BASE.date(), "运动 30 分钟", "愉快", "今天散步了。", ["运动", "生活"])
    diary = repository.get_diary("2026-10-02")
    assert diary["tags"] == ["运动", "生活"]
    assert diary["body"] == "今天散步了。"
    assert repository.daily_summary(BASE.date())["total"] == 0
    assert repository.get_diary("2026-10-01")["tags"] == []


def test_settings_keep_native_types(repository):
    for key, value in {"mode": "active", "idle_threshold_seconds": 300, "reminder_enabled": True, "tags": ["学习"]}.items():
        repository.set_setting(key, value)
        assert repository.get_setting(key) == value
    assert repository.get_setting("missing", "fallback") == "fallback"


def test_export_all_record_kinds_json_and_csv(repository, tmp_path):
    repository.append_segments([segment()])
    repository.save_diary(BASE.date(), "完成", "平静", "正文", ["学习"])
    repository.set_setting("mode", "foreground")
    json_path, csv_path = tmp_path / "data.json", tmp_path / "data.csv"
    repository.export(json_path)
    repository.export(csv_path, "csv")
    exported = json.loads(json_path.read_text(encoding="utf-8"))
    assert set(exported) == {"schema_version", "sessions", "apps", "diaries", "settings"}
    assert exported["sessions"][0]["seconds"] == 2
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert {row["record_type"] for row in rows} == {"automatic", "app", "diary", "setting"}
    automatic = next(row for row in rows if row["record_type"] == "automatic")
    assert automatic["app_name"] == "VS Code"
    assert automatic["category"] == "学习与编程"
    assert automatic["day"] == "2026-10-02"
    assert float(automatic["seconds"]) == exported["sessions"][0]["seconds"]
    diary = next(row for row in rows if row["record_type"] == "diary")
    assert diary["completed"] == "完成"
    assert diary["mood"] == "平静"
    assert diary["body"] == "正文"
    assert json.loads(diary["tags"]) == ["学习"]
    assert diary["seconds"] == ""
    setting = next(row for row in rows if row["record_type"] == "setting")
    assert setting["key"] == "mode"
    assert json.loads(setting["value"]) == "foreground"


def test_backup_restore_and_failed_restore_preserves_history(repository, tmp_path):
    repository.append_segments([segment()])
    repository.save_diary(BASE.date(), "完成", "愉快", "日记", ["tag"])
    repository.set_setting("theme", "dark")
    backup = tmp_path / "backup.sqlite3"
    repository.backup(backup)
    repository.clear_history()
    assert repository.daily_summary(BASE.date())["total"] == 0
    repository.restore(backup)
    assert repository.daily_summary(BASE.date())["total"] == 2
    assert repository.get_diary(BASE.date())["body"] == "日记"
    assert repository.get_setting("theme") == "dark"
    invalid = tmp_path / "invalid.sqlite3"
    invalid.write_bytes(b"not sqlite")
    with pytest.raises((ValueError, sqlite3.DatabaseError)):
        repository.restore(invalid)
    assert repository.daily_summary(BASE.date())["total"] == 2


def test_restore_constraint_failure_rolls_back_existing_data(repository, tmp_path):
    repository.append_segments([segment()])
    backup = tmp_path / "bad_backup.sqlite3"
    repository.backup(backup)
    connection = sqlite3.connect(backup)
    connection.execute("PRAGMA ignore_check_constraints=ON")
    connection.execute("UPDATE sessions SET mode='bad'")
    connection.commit()
    connection.close()
    with pytest.raises(ValueError):
        repository.restore(backup)
    assert repository.daily_summary(BASE.date())["total"] == 2


def test_delete_one_date_and_clear_history_preserve_app_preferences(repository):
    repository.append_segments([segment()])
    tomorrow = BASE + timedelta(days=1)
    repository.append_segments([Segment(B, tomorrow, tomorrow + timedelta(seconds=3), 3)])
    repository.save_diary(BASE.date(), "", "", "diary", [])
    repository.set_setting("mode", "active")
    repository.delete_date(BASE.date())
    assert repository.daily_summary(BASE.date())["total"] == 0
    assert repository.get_diary(BASE.date())["body"] == ""
    assert repository.daily_summary(tomorrow.date())["total"] == 3
    repository.clear_history()
    assert repository.daily_summary(tomorrow.date())["total"] == 0
    assert repository.get_setting("mode") == "active"
    assert len(repository.list_apps()) == 2


def test_transaction_failure_does_not_partially_ingest(repository):
    bad = Segment(A, BASE + timedelta(seconds=2), BASE + timedelta(seconds=4), 2, "invalid")
    with pytest.raises(ValueError):
        repository.append_segments([segment(), bad])
    assert repository.daily_summary(BASE.date())["total"] == 0
    repository.append_segments([segment()])
    assert repository.daily_summary(BASE.date())["total"] == 2


def test_repository_is_thread_safe(repository):
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda offset: repository.append_segments([segment(offset * 2)]), range(50)))
    assert repository.daily_summary(BASE.date())["total"] == 100


def test_unsupported_database_version_is_never_overwritten(tmp_path):
    path = tmp_path / "future.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA user_version=99")
    connection.close()
    with pytest.raises(ValueError):
        Repository(path)
    connection = sqlite3.connect(path)
    assert connection.execute("PRAGMA user_version").fetchone()[0] == 99
    connection.close()


@pytest.mark.parametrize("key,value", [
    ("mode", "background"), ("idle_threshold_seconds", "300"),
    ("idle_threshold_seconds", -1), ("poll_interval_seconds", 0),
    ("theme", {}), ("reminder_time", "25:99"), ("reminder_enabled", "true"),
    ("autostart", 1), ("tags", [123]),
])
def test_invalid_restore_settings_preserve_current_history(repository, tmp_path, key, value):
    repository.append_segments([segment()])
    backup = tmp_path / "backup.sqlite3"
    repository.backup(backup)
    connection = sqlite3.connect(backup)
    connection.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (key, json.dumps(value)))
    connection.commit()
    connection.close()
    with pytest.raises(ValueError):
        repository.restore(backup)
    assert repository.daily_summary(BASE.date())["total"] == 2
    assert repository.get_setting(key) is None


@pytest.mark.parametrize("table,assignment", [
    ("sessions", "start='invalid'"), ("sessions", "day='2026-10-01'"),
    ("sessions", "seconds=1e999"), ("diaries", "tags='[123]'"),
    ("diaries", "date='invalid'"), ("apps", "category='invalid'"),
])
def test_invalid_restore_record_formats_preserve_history(repository, tmp_path, table, assignment):
    repository.append_segments([segment()])
    repository.save_diary(BASE.date(), "", "", "original", [])
    backup = tmp_path / "backup.sqlite3"
    repository.backup(backup)
    connection = sqlite3.connect(backup)
    connection.execute(f"UPDATE {table} SET {assignment}")
    connection.commit()
    connection.close()
    with pytest.raises(ValueError):
        repository.restore(backup)
    assert repository.daily_summary(BASE.date())["total"] == 2
    assert repository.get_diary(BASE.date())["body"] == "original"


def test_csv_automatic_totals_match_database_and_never_count_diaries(repository, tmp_path):
    repository.append_segments([segment(0, 2), segment(2, 3, B), segment(6, 1)])
    repository.save_diary(BASE.date(), "运动 300 秒", "开心", "外出 30 分钟", ["运动"])
    output = tmp_path / "history.csv"
    repository.export(output, "csv")
    with output.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    automatic = [row for row in rows if row["record_type"] == "automatic"]
    assert sum(float(row["seconds"]) for row in automatic) == repository.daily_summary(BASE.date())["total"] == 6
    assert sum(float(row["seconds"]) for row in automatic if row["app_key"] == A.key) == 3
    assert all(row["seconds"] == "" for row in rows if row["record_type"] != "automatic")


@pytest.mark.parametrize("value", ["=SUM(1,1)", "+123", "-danger", "@command", "\ttext", "\rtext", "\ntext", "  =formula"])
def test_csv_protects_formula_text_but_json_preserves_original(repository, tmp_path, value):
    repository.append_segments([segment()])
    repository.update_app(A.key, name=value, icon=value)
    repository.save_diary(BASE.date(), value, value, value, [value])
    repository.set_setting(value, value)
    csv_path = tmp_path / "safe.csv"
    json_path = tmp_path / "original.json"
    repository.export(csv_path, "csv")
    repository.export(json_path, "json")
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    app_row = next(row for row in rows if row["record_type"] == "app")
    diary_row = next(row for row in rows if row["record_type"] == "diary")
    setting_row = next(row for row in rows if row["record_type"] == "setting")
    assert app_row["name"] == "'" + value
    assert app_row["icon"] == "'" + value
    assert diary_row["body"] == "'" + value
    assert diary_row["completed"] == "'" + value
    assert diary_row["mood"] == "'" + value
    assert setting_row["key"] == "'" + value
    assert json.loads(diary_row["tags"]) == [value]
    exported = json.loads(json_path.read_text(encoding="utf-8"))
    assert exported["apps"][0]["name"] == value
    assert exported["apps"][0]["icon"] == value
    assert exported["diaries"][0]["body"] == value
    assert json.loads(exported["diaries"][0]["tags"]) == [value]
    assert exported["settings"][0]["key"] == value
    assert json.loads(exported["settings"][0]["value"]) == value
