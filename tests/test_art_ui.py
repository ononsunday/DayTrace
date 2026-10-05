"""新版美术界面的操作回归，使用真实 SQLite 与 Qt 控件。"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QDate, QEvent, QObject, Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

from daytrace.core.repository import Repository
from daytrace.ui.main_window import MainWindow


@pytest.fixture(scope="session")
def art_app():
    app = QApplication.instance() or QApplication([])
    if os.name == "nt" and not QFontDatabase.families():
        for filename in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf", "seguisb.ttf"):
            QFontDatabase.addApplicationFont(f"C:/Windows/Fonts/{filename}")
    return app


class AuditedRepository(Repository):
    def __init__(self, path):
        super().__init__(path)
        self.report_queries = []

    def daily_summary(self, day):
        self.report_queries.append(("summary", day))
        return super().daily_summary(day)

    def trend(self, end_date, days):
        self.report_queries.append(("trend", days))
        return super().trend(end_date, days)

    def list_apps(self):
        self.report_queries.append(("apps", None))
        return super().list_apps()


@pytest.fixture
def art_gui(art_app, tmp_path, monkeypatch):
    repository = AuditedRepository(tmp_path / "daytrace-art.db")
    calls, warnings = [], []

    def settings_changed(options):
        calls.append(dict(options))
        for key, value in options.items():
            repository.set_setting(key, value)
        return True

    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: warnings.append(args[2]))
    window = MainWindow(repository, {"settings_changed": settings_changed})
    window.allow_close = True
    window.show()
    art_app.processEvents()
    yield window, repository, calls, warnings
    window.close()
    window.deleteLater()
    art_app.processEvents()
    repository.close()


def click_date(window, action):
    button = window.findChild(QPushButton, action)
    assert button is not None
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)


def test_local_art_loaded_and_twelve_labeled_sticker_actions_exist(art_gui):
    window, repository, calls, warnings = art_gui
    assert not window.artwork.main.isNull()
    assert not window.artwork.backdrop.isNull()
    assert len(window.artwork.stickers) == 12
    assert all(not icon.isNull() for icon in window.artwork.stickers)
    buttons = [button for button in window.findChildren(QPushButton) if button.property("stickerIndex") is not None]
    assert len(buttons) == 12
    assert {button.property("stickerIndex") for button in buttons} == set(range(12))
    for button in buttons:
        assert any("\u4e00" <= character <= "\u9fff" for character in button.text())
        assert button.accessibleName().strip()
        assert not button.icon().isNull()
    assert calls == []
    assert warnings == []


@pytest.mark.parametrize("action,offset", [("date_previous", -1), ("date_next", 1), ("date_today", None)])
def test_sticker_date_navigation_preserves_unsaved_diary_on_original_day(art_gui, art_app, action, offset):
    window, repository, calls, warnings = art_gui
    original = QDate.currentDate().addDays(-7)
    expected = QDate.currentDate() if offset is None else original.addDays(offset)
    window.select_date(original)
    window.show_page(3)
    diary = window.pages[3]
    diary.body.setPlainText("切换前还没等到自动保存的日记。")
    diary.completed.setPlainText("出去散步了")
    diary.tags.setText("日常，散步")
    diary.mood.setCurrentText("开心")
    click_date(window, action)
    assert window.selected_date == expected
    assert window.date_edit.date() == expected
    assert diary.calendar.selectedDate() == expected
    saved = repository.get_diary(original.toString("yyyy-MM-dd"))
    assert saved["body"] == "切换前还没等到自动保存的日记。"
    assert saved["completed"] == "出去散步了"
    assert saved["mood"] == "开心"
    assert saved["tags"] == ["日常", "散步"]
    assert diary.body.toPlainText() == ""
    assert repository.get_diary(expected.toString("yyyy-MM-dd"))["body"] == ""
    # 等待原防抖窗口经过，确保旧 timer 没有把文本写入新日期。
    QTest.qWait(700)
    assert repository.get_diary(expected.toString("yyyy-MM-dd"))["body"] == ""
    assert repository.daily_summary(original.toString("yyyy-MM-dd"))["total"] == 0


@pytest.mark.parametrize("action", ["date_previous", "date_next", "date_today"])
def test_sticker_date_navigation_stays_put_when_diary_save_fails(art_gui, action, monkeypatch):
    window, repository, calls, warnings = art_gui
    original = QDate.currentDate().addDays(-7)
    window.select_date(original)
    window.show_page(3)
    diary = window.pages[3]
    diary.body.setPlainText("保存失败时仍必须保留的原始正文。")
    save_diary = repository.save_diary

    def fail_save(*args, **kwargs):
        raise OSError("simulated disk full")

    monkeypatch.setattr(repository, "save_diary", fail_save)
    click_date(window, action)
    assert window.selected_date == window.date_edit.date() == diary.calendar.selectedDate() == original
    assert diary.body.toPlainText() == "保存失败时仍必须保留的原始正文。"
    assert diary.dirty
    assert "保存失败" in diary.saved.text()
    monkeypatch.setattr(repository, "save_diary", save_diary)
    assert window.flush_diary()
    assert repository.get_diary(original.toString("yyyy-MM-dd"))["body"] == "保存失败时仍必须保留的原始正文。"


def test_overview_mode_selector_changes_only_foreground_or_active_once(art_gui, art_app):
    window, repository, calls, warnings = art_gui
    picker = window.mode_selector
    assert picker.objectName() == "mode_selector"
    assert {picker.itemData(index) for index in range(picker.count())} == {"foreground", "active"}
    assert picker.count() == 2
    picker.setCurrentIndex(picker.findData("active"))
    art_app.processEvents()
    window.refresh()
    assert [call["mode"] for call in calls] == ["active"]
    assert picker.currentData() == repository.get_setting("mode") == "active"
    picker.setCurrentIndex(picker.findData("foreground"))
    art_app.processEvents()
    assert [call["mode"] for call in calls] == ["active", "foreground"]
    assert picker.currentData() == repository.get_setting("mode") == "foreground"
    assert warnings == []


@pytest.mark.parametrize("raises", [False, True])
def test_overview_mode_selector_rolls_back_failed_controller_change(art_gui, raises):
    window, repository, calls, warnings = art_gui
    repository.set_setting("mode", "foreground")

    def refuse(options):
        calls.append(dict(options))
        if raises:
            raise OSError("simulated tracking reconfiguration failure")
        return False

    window.actions["settings_changed"] = refuse
    window.mode_selector.setCurrentIndex(window.mode_selector.findData("active"))
    assert [call["mode"] for call in calls] == ["active"]
    assert repository.get_setting("mode") == window.mode_selector.currentData() == "foreground"
    assert "保留原模式" in window.mode_selector.toolTip()
    if raises:
        assert len(warnings) == 1
        assert "simulated tracking" in warnings[0]


def test_mode_selector_authoritative_reload_has_no_change_callback(art_gui):
    window, repository, calls, warnings = art_gui
    window.show_page(5)
    settings = window.pages[5]
    window.show_page(0)
    repository.set_setting("mode", "active")
    window.reload_after_restore()
    assert window.mode_selector.currentData() == "active"
    assert settings.mode.currentData() == "active"
    assert calls == []
    window.mode_selector.setCurrentIndex(window.mode_selector.findData("foreground"))
    assert settings.mode.currentData() == "foreground"
    assert [call["mode"] for call in calls] == ["foreground"]


def test_sticker_shortcuts_open_their_destination_without_extra_pages(art_gui):
    window, repository, calls, warnings = art_gui
    assert set(window.pages) == {0}
    QTest.mouseClick(window.pages[0].diary_button, Qt.MouseButton.LeftButton)
    assert window.current_page == 3
    assert set(window.pages) == {0, 3}
    window.pages[3].body.setPlainText("点击导航之前的内容。")
    QTest.mouseClick(window.nav[0], Qt.MouseButton.LeftButton)
    assert window.current_page == 0
    assert repository.get_diary(window.selected_date.toString("yyyy-MM-dd"))["body"] == "点击导航之前的内容。"
    QTest.mouseClick(window.pages[0].timeline_button, Qt.MouseButton.LeftButton)
    assert window.current_page == 1
    assert set(window.pages) == {0, 1, 3}


class PaintProbe(QObject):
    def __init__(self, parent):
        super().__init__(parent)
        self.paints = []

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Paint:
            self.paints.append(watched)
        return False


def test_hidden_statistics_page_is_not_queried_or_painted_on_overview_refresh(art_gui, art_app):
    window, repository, calls, warnings = art_gui
    window.show_page(2)
    art_app.processEvents()
    analytics = window.pages[2]
    charts = [analytics.bar, analytics.line]
    probe = PaintProbe(window)
    for chart in charts:
        chart.installEventFilter(probe)
    window.show_page(0)
    art_app.processEvents()
    probe.paints.clear()
    repository.report_queries.clear()
    window.refresh()
    art_app.processEvents()
    assert any(query[0] == "summary" for query in repository.report_queries)
    assert all(query[0] != "trend" for query in repository.report_queries)
    assert probe.paints == []
    window.hide()
    art_app.processEvents()
    repository.report_queries.clear()
    probe.paints.clear()
    for _ in range(3):
        window.refresh()
        window.centralWidget().update()
        art_app.processEvents()
    assert repository.report_queries == []
    assert probe.paints == []
