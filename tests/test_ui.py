"""无屏幕 Qt 测试，验证日记持久化、页面惰性查询与真实数据库展示。"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime, timedelta

import pytest
from PySide6.QtCore import QDate
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from daytrace.core.models import AppIdentity, Segment
from daytrace.core.repository import Repository
from daytrace.ui.main_window import MainWindow


@pytest.fixture(scope="session")
def qt_app():
    app = QApplication.instance() or QApplication([])
    # Windows 的 offscreen 后端不枚举系统字体，显式注册以检验中文字形。
    if os.name == "nt" and not QFontDatabase.families():
        for filename in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf", "seguisb.ttf"):
            QFontDatabase.addApplicationFont(f"C:/Windows/Fonts/{filename}")
    return app


class CountingRepository(Repository):
    def __init__(self, path):
        super().__init__(path)
        self.queries = []

    def daily_summary(self, day):
        self.queries.append(("summary", day))
        return super().daily_summary(day)

    def trend(self, end_date, days):
        self.queries.append(("trend", days))
        return super().trend(end_date, days)

    def list_apps(self):
        self.queries.append(("apps", None))
        return super().list_apps()


@pytest.fixture
def gui(qt_app, tmp_path):
    repo = CountingRepository(tmp_path / "daytrace.db")
    window = MainWindow(repo)
    window.allow_close = True
    window.show()
    qt_app.processEvents()
    yield window, repo
    window.close()
    window.deleteLater()
    qt_app.processEvents()
    repo.close()


def add_record(repo, day="2026-10-03", seconds=3600):
    start = datetime.fromisoformat(f"{day}T09:00:00")
    repo.append_segments([Segment(AppIdentity("code.exe", "VS Code", "code.exe"), start, start + timedelta(seconds=seconds), seconds)])


def test_pages_lazy_and_hidden_refresh_performs_no_queries(gui, qt_app):
    window, repo = gui
    assert list(window.pages) == [0]
    window.show_page(2)
    assert set(window.pages) == {0, 2}
    repo.queries.clear()
    window.refresh()
    assert any(query[0] == "trend" for query in repo.queries)
    assert not any(query[0] == "apps" for query in repo.queries)
    window.hide()
    repo.queries.clear()
    window.refresh()
    assert repo.queries == []


def test_every_page_renders_empty_and_real_data(gui, qt_app):
    window, repo = gui
    window.select_date("2026-10-03")
    for index in range(6):
        window.show_page(index)
        qt_app.processEvents()
        assert not window.grab().isNull()
    add_record(repo)
    window.show_page(0)
    assert window.pages[0].total.text() == "1 小时 0 分钟"
    assert window.pages[0].top.text() == "VS Code"
    window.show_page(1)
    assert window.pages[1].table.rowCount() == 1
    window.show_page(2)
    assert window.pages[2].bar.data[0]["seconds"] == 3600
    assert sum(r["seconds"] for r in window.pages[2].line.data) == 3600
    qt_app.processEvents()
    assert not window.grab().isNull()
    window.show_page(3)
    report = window.pages[3].report.toPlainText()
    assert "09:00:00～10:00:00  VS Code" in report
    assert "手动记录 · 生活日记（不计入电脑时长）" in report


def test_diary_autosave_and_navigation_keep_original_date(gui, qt_app):
    window, repo = gui
    window.select_date("2026-10-03")
    window.show_page(3)
    diary = window.pages[3]
    diary.completed.setPlainText("跑步 30 分钟")
    diary.body.setPlainText("吃到了喜欢的饭。")
    diary.tags.setText("运动，日常")
    QTest.qWait(800)
    assert repo.get_diary("2026-10-03")["body"] == "吃到了喜欢的饭。"
    assert repo.get_diary("2026-10-03")["tags"] == ["运动", "日常"]
    assert repo.daily_summary("2026-10-03")["total"] == 0
    diary.body.setPlainText("切换日期之前保存。")
    window.select_date("2026-10-04")
    assert repo.get_diary("2026-10-03")["body"] == "切换日期之前保存。"
    assert diary.body.toPlainText() == ""
    assert repo.get_diary("2026-10-04")["body"] == ""


def test_deleted_diary_is_not_resurrected_by_cache(gui):
    window, repo = gui
    window.select_date("2026-10-03")
    window.show_page(3)
    diary = window.pages[3]
    diary.body.setPlainText("准备删除")
    window.flush_diary()
    repo.delete_date("2026-10-03")
    window.refresh()
    assert diary.body.toPlainText() == ""
    assert diary.dirty is False
    window.select_date("2026-10-04")
    assert repo.get_diary("2026-10-03")["body"] == ""


def test_restore_reloads_theme_and_diary_without_old_writes(gui, tmp_path):
    window, repo = gui
    window.select_date("2026-10-03")
    window.show_page(3)
    diary = window.pages[3]
    diary.body.setPlainText("旧数据库")
    window.flush_diary()
    restored = Repository(tmp_path / "other.db")
    restored.save_diary("2026-10-03", "", "平静", "备份里的日记", [])
    restored.set_setting("theme", "dark")
    restored.backup(tmp_path / "backup.db")
    restored.close()
    repo.restore(tmp_path / "backup.db")
    window.reload_after_restore()
    assert window.theme == "dark"
    assert diary.body.toPlainText() == "备份里的日记"
    assert repo.get_diary("2026-10-03")["body"] == "备份里的日记"


def test_settings_commit_active_mode_without_background_mode(gui):
    window, repo = gui
    window.show_page(5)
    page = window.pages[5]
    assert page.mode.count() == 2
    page.mode.setCurrentIndex(1)
    page.idle.setValue(8)
    page.theme_choice.setCurrentIndex(1)
    page.save()
    assert repo.get_setting("mode") == "active"
    assert repo.get_setting("idle_threshold_seconds") == 480
    assert window.theme == "dark"


def test_close_hides_only_when_tray_available(gui, qt_app, monkeypatch):
    window, repo = gui
    window.allow_close = False
    window.tray_available = True
    window.close()
    assert not window.isVisible()
    window.show()
    window.tray_available = False
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.No)
    window.close()
    assert window.isVisible()
    window.allow_close = True


def test_failed_diary_save_blocks_date_change(gui, monkeypatch):
    window, repo = gui
    window.select_date("2026-10-03")
    window.show_page(3)
    diary = window.pages[3]
    diary.body.setPlainText("不能丢失的内容")
    original = repo.save_diary

    def disk_error(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(repo, "save_diary", disk_error)
    window.select_date("2026-10-04")
    assert window.selected_date == QDate(2026, 10, 3)
    assert diary.body.toPlainText() == "不能丢失的内容"
    assert diary.dirty
    monkeypatch.setattr(repo, "save_diary", original)
