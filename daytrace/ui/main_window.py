"""DayTrace 桌面界面。页面惰性加载，隐藏时不轮询统计数据。"""
from __future__ import annotations

import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QDate, QFileInfo, QSize, Qt, QTime, QTimer, Signal, QSignalBlocker
from PySide6.QtGui import QColor, QCloseEvent, QFont, QIcon, QPainter, QPen, QPixmap, QTextCharFormat
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCalendarWidget, QCheckBox, QComboBox, QDateEdit,
    QDialog, QDialogButtonBox, QFileDialog, QFileIconProvider, QFormLayout, QFrame,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QPushButton, QScrollArea, QSizePolicy, QSpinBox, QStackedWidget,
    QTableWidget, QTableWidgetItem, QTextEdit, QTimeEdit, QVBoxLayout, QWidget,
)

from .charts import DonutChart, HorizontalBarChart, TrendChart, duration_text
from .theme import CATEGORIES, apply_theme, category_color, colors
from .artwork import Artwork, DecorativeCard, IllustratedHero, SceneryShell, ScenerySidebar, butterfly, sticker_button


def label(text: str = "", role: str | None = None, wrap: bool = False) -> QLabel:
    result = QLabel(text)
    result.setTextFormat(Qt.TextFormat.PlainText)
    result.setWordWrap(wrap)
    if role:
        result.setProperty("role", role)
    return result


def button(text: str, callback: Callable | None = None, role: str | None = None) -> QPushButton:
    result = QPushButton(text)
    if role:
        result.setProperty("role", role)
    if callback:
        result.clicked.connect(callback)
    return result


def card(title: str = "", subtitle: str = "") -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("Card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(22, 20, 22, 20)
    layout.setSpacing(12)
    if title:
        layout.addWidget(label(title, "subheading"))
    if subtitle:
        layout.addWidget(label(subtitle, "muted", True))
    return frame, layout


def time_text(value) -> str:
    try:
        if isinstance(value, (int, float)):
            value = datetime.fromtimestamp(value)
        elif isinstance(value, str):
            value = datetime.fromisoformat(value)
        return value.strftime("%H:%M:%S")
    except (ValueError, TypeError, AttributeError, OSError):
        return "—"


def app_icon(row: dict) -> QIcon:
    """仅提取本地程序图标，不读取窗口标题或应用内容。"""
    custom = str(row.get("icon") or "")
    executable = str(row.get("executable") or "")
    try:
        if custom and Path(custom).is_file():
            icon = QIcon(custom)
            if not icon.isNull():
                return icon
        if executable and Path(executable).is_file():
            return QFileIconProvider().icon(QFileInfo(executable))
    except (OSError, ValueError):
        pass
    pixmap = QPixmap(28, 28)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(category_color(str(row.get("category", "其他"))))
    painter.drawRoundedRect(1, 1, 26, 26, 7, 7)
    painter.setPen(QColor("#ffffff"))
    painter.setFont(QFont("Microsoft YaHei UI", 10, QFont.Weight.DemiBold))
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, str(row.get("name") or "?")[:1])
    painter.end()
    return QIcon(pixmap)


def create_table(headers: list[str]) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    table.setShowGrid(False)
    table.verticalHeader().hide()
    table.verticalHeader().setDefaultSectionSize(47)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    table.setIconSize(QSize(24, 24))
    table.setAlternatingRowColors(False)
    table.setMinimumHeight(190)
    return table


def fill_timeline(table: QTableWidget, rows: list[dict], limit: int | None = None) -> None:
    rows = rows[:limit] if limit else rows
    table.setRowCount(len(rows))
    for index, row in enumerate(rows):
        name = QTableWidgetItem(str(row.get("name", "未知应用")))
        name.setIcon(app_icon(row))
        name.setToolTip(str(row.get("name", "未知应用")))
        table.setItem(index, 0, name)
        for column, value in enumerate((time_text(row.get("start")), time_text(row.get("end")), duration_text(row.get("seconds", 0), compact=True), row.get("category", "其他")), 1):
            table.setItem(index, column, QTableWidgetItem(str(value)))


class BrandMark(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(40, 40)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        butterfly(painter, 20, 18, 17, QColor("#df8fb5"), -12)


def navigation_icon(index: int) -> QIcon:
    """用矢量笔画生成图标，避免符号字体缺字；开销仅在窗口创建时发生。"""
    icon = QIcon()
    for state, color in ((QIcon.State.Off, "#817686"), (QIcon.State.On, "#c9638d")):
        pixmap = QPixmap(20, 20)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(color), 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if index == 0:
            painter.drawEllipse(3, 3, 14, 14)
            painter.drawLine(10, 6, 10, 10)
            painter.drawLine(10, 10, 13, 12)
        elif index == 1:
            painter.drawLine(5, 4, 5, 16)
            for y in (4, 10, 16):
                painter.drawEllipse(3, y - 2, 4, 4)
                painter.drawLine(10, y, 17, y)
        elif index == 2:
            painter.drawLine(3, 17, 17, 17)
            for x, y in ((5, 10), (10, 4), (15, 7)):
                painter.drawLine(x, y, x, 14)
        elif index == 3:
            painter.drawRoundedRect(3, 3, 13, 14, 2, 2)
            painter.drawLine(7, 7, 13, 7)
            painter.drawLine(7, 10, 13, 10)
            painter.drawLine(7, 13, 10, 13)
        elif index == 4:
            for x in (3, 12):
                for y in (3, 12):
                    painter.drawRoundedRect(x, y, 5, 5, 1, 1)
        else:
            painter.drawEllipse(5, 5, 10, 10)
            painter.drawEllipse(8, 8, 4, 4)
            for x1, y1, x2, y2 in ((10, 2, 10, 4), (10, 16, 10, 18), (2, 10, 4, 10), (16, 10, 18, 10), (4, 4, 5, 5), (15, 15, 16, 16), (4, 16, 5, 15), (15, 5, 16, 4)):
                painter.drawLine(x1, y1, x2, y2)
        painter.end()
        icon.addPixmap(pixmap, QIcon.Mode.Normal, state)
    return icon


class Page(QWidget):
    def __init__(self, window: "MainWindow") -> None:
        super().__init__()
        self.window = window
        self.repo = window.repository
        self.setObjectName("Page")
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(18)

    @property
    def date(self) -> str:
        return self.window.selected_date.toString("yyyy-MM-dd")

    def refresh(self) -> None:
        pass

    def flush(self) -> None:
        pass


class OverviewPage(Page):
    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        hero = IllustratedHero(window.artwork)
        self.hero = hero
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(25, 21, 25, 20)
        hero.content_panel = QWidget()
        hero.content_panel.setObjectName("HeroContent")
        hero.content_panel.setFixedWidth(450)
        metric_layout = QVBoxLayout(hero.content_panel)
        metric_layout.setContentsMargins(0, 0, 0, 0)
        metric_layout.setSpacing(10)
        metric_layout.addWidget(label("今日电脑使用", "subheading"))
        self.total = label("0 秒", "metric")
        self._total_value = "0 秒"
        self.total.setObjectName("OverviewTotal")
        self.total.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.total.setWordWrap(True)
        total_row = QHBoxLayout()
        total_row.addWidget(self.total, 1)
        badge = label("自动记录")
        badge.setObjectName("AutoBadge")
        total_row.addWidget(badge, 0, Qt.AlignmentFlag.AlignVCenter)
        metric_layout.addLayout(total_row)
        self.note = label("只记录前台软件，让每一天有迹可循。", "muted", True)
        metric_layout.addWidget(self.note)
        top_frame = QFrame()
        top_frame.setObjectName("TopApp")
        top_layout = QHBoxLayout(top_frame)
        top_layout.setContentsMargins(13, 10, 13, 10)
        top_layout.setSpacing(8)
        top_layout.addWidget(label("使用最多", "muted"))
        self.top_icon = QLabel()
        self.top_icon.setFixedSize(26, 26)
        top_layout.addWidget(self.top_icon)
        self.top = label("等待第一条记录", "subheading", True)
        self.top.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.top_time = label("", "muted")
        top_layout.addWidget(self.top, 1)
        top_layout.addWidget(self.top_time)
        metric_layout.addWidget(top_frame)
        hero_layout.addWidget(hero.content_panel)
        hero_layout.addStretch(1)
        self.layout.addWidget(hero)
        row = QHBoxLayout()
        row.setSpacing(18)
        category_frame = DecorativeCard()
        category_layout = QVBoxLayout(category_frame)
        category_layout.setContentsMargins(20, 16, 20, 16)
        category_layout.setSpacing(9)
        category_layout.addWidget(label("分类分布", "subheading"))
        category_row = QHBoxLayout()
        self.donut = DonutChart()
        self.donut.setMinimumWidth(140)
        self.donut.setMinimumHeight(165)
        self.donut.setMaximumWidth(190)
        category_row.addWidget(self.donut)
        self.legend = label("还没有分类数据", "muted", True)
        self.legend.setMinimumWidth(105)
        self.legend.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        category_row.addWidget(self.legend, 1)
        category_layout.addLayout(category_row)
        row.addWidget(category_frame, 3)
        diary_frame = DecorativeCard("butterfly")
        diary_layout = QVBoxLayout(diary_frame)
        diary_layout.setContentsMargins(20, 16, 20, 16)
        diary_layout.setSpacing(9)
        diary_title = QHBoxLayout()
        diary_title.addWidget(label("生活记录", "subheading"))
        manual = label("手动填写")
        manual.setObjectName("ManualBadge")
        diary_title.addWidget(manual)
        diary_title.addStretch()
        diary_title.addSpacing(17)
        diary_layout.addLayout(diary_title)
        self.diary_preview = label("今天有什么想记下的？", "muted", True)
        self.diary_preview.setObjectName("DiaryPreview")
        self.diary_preview.setMinimumHeight(65)
        self.diary_preview.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        diary_layout.addWidget(self.diary_preview, 1)
        diary_tools = QHBoxLayout()
        diary_tools.addWidget(label("不计入电脑时长", "muted"), 1)
        self.diary_button = sticker_button(button("写一笔", lambda: window.show_page(3), "primary"), window.artwork, 10, size=36, fallback=navigation_icon(3))
        self.diary_button.setObjectName("action_diary")
        diary_tools.addWidget(self.diary_button)
        diary_layout.addLayout(diary_tools)
        row.addWidget(diary_frame, 2)
        self.layout.addLayout(row)
        timeline_frame = DecorativeCard()
        timeline_layout = QVBoxLayout(timeline_frame)
        timeline_layout.setContentsMargins(19, 15, 19, 14)
        timeline_layout.setSpacing(9)
        timeline_title = QHBoxLayout()
        timeline_title.addWidget(label("今日时间轴", "subheading"), 1)
        self.timeline_button = sticker_button(button("完整时间轴", lambda: window.show_page(1)), window.artwork, 11, size=34, fallback=navigation_icon(1))
        self.timeline_button.setObjectName("action_timeline")
        timeline_title.addWidget(self.timeline_button)
        timeline_layout.addLayout(timeline_title)
        self.timeline = create_table(["应用", "开始", "结束", "时长", "分类"])
        self.timeline.setMinimumHeight(160)
        timeline_layout.addWidget(self.timeline)
        self.empty = label("还没有记录。统计服务运行后，会自动保存前台应用的使用时间。", "muted", True)
        timeline_layout.addWidget(self.empty)
        self.layout.addWidget(timeline_frame)
        self.layout.addStretch()

    def refresh(self) -> None:
        summary = self.repo.daily_summary(self.date)
        total = summary.get("total", 0)
        self._total_value = duration_text(total)
        self.update_total_label()
        apps = sorted(summary.get("apps", []), key=lambda row: row["seconds"], reverse=True)
        self.top.setText(apps[0]["name"] if apps else "等待第一条记录")
        self.top.setToolTip(apps[0]["name"] if apps else "打开其他软件后，将自动积累记录。")
        self.top_time.setText(duration_text(apps[0]["seconds"], compact=True) if apps else "")
        self.top_icon.setVisible(bool(apps))
        if apps:
            self.top_icon.setPixmap(app_icon(apps[0]).pixmap(26, 26))
        self.donut.set_data(summary.get("categories", []))
        categories = sorted(summary.get("categories", []), key=lambda row: row["seconds"], reverse=True)
        self.legend.setText("\n\n".join(f"{r['category']}  {r['seconds'] / total:.0%}\n{duration_text(r['seconds'], compact=True)}" for r in categories[:7]) if total else "还没有分类数据\n使用其他软件后自动统计")
        rows = summary.get("timeline", [])
        fill_timeline(self.timeline, list(reversed(rows)), 5)
        self.empty.setVisible(not rows)
        self.timeline.setVisible(bool(rows))
        diary = self.repo.get_diary(self.date) or {}
        text = str(diary.get("body") or diary.get("completed") or "今天有什么想记下的？\n心情、标签，或者一件日常小事。")
        self.diary_preview.setText(text[:125] + ("…" if len(text) > 125 else ""))
        mode = self.repo.get_setting("mode", "foreground")
        self.note.setText("活跃模式 · 空闲、锁屏、休眠和暂停期间不累计。" if mode == "active" else "前台模式 · 锁屏、休眠和暂停期间不累计。")

    def update_total_label(self) -> None:
        text = self._total_value
        if self.window.width() < 1050:
            # 数值与单位不可断开；窄窗口可在“小时”和“分钟”两组之间自然换行。
            for unit in ("小时", "分钟", "秒"):
                text = text.replace(f" {unit}", f"\N{NO-BREAK SPACE}{unit}")
        self.total.setText(text)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_total_value"):
            self.update_total_label()


class TimelinePage(Page):
    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        frame, layout = card("应用切换时间轴", "每条记录只属于一个前台应用。跨午夜记录按日期拆分。")
        tools = QHBoxLayout()
        self.simplify = QCheckBox("简化显示：隐藏不足 5 秒的记录")
        self.simplify.stateChanged.connect(self.refresh)
        tools.addWidget(self.simplify)
        tools.addStretch()
        self.count = label("", "muted")
        tools.addWidget(self.count)
        layout.addLayout(tools)
        self.table = create_table(["应用", "开始", "结束", "有效时长", "分类"])
        self.table.setMinimumHeight(400)
        layout.addWidget(self.table)
        self.empty = label("这一天还没有使用记录。", "muted", True)
        layout.addWidget(self.empty)
        layout.addWidget(label("简化只影响显示，汇总时长仍来自完整记录；检测间隔内未被观察到的切换无法精确还原。", "muted", True))
        self.layout.addWidget(frame)
        self.layout.addStretch()

    def refresh(self) -> None:
        summary = self.repo.daily_summary(self.date)
        rows = summary.get("timeline", [])
        visible = [r for r in rows if float(r["seconds"]) >= 5] if self.simplify.isChecked() else rows
        fill_timeline(self.table, list(reversed(visible)))
        self.count.setText(f"{len(visible)} / {len(rows)} 条 · {duration_text(summary.get('total', 0))}")
        self.empty.setText("暂无满足筛选条件的记录。" if rows else "这一天还没有使用记录。")
        self.empty.setVisible(not visible)
        self.table.setVisible(bool(visible))


class AnalyticsPage(Page):
    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        top = QHBoxLayout()
        top.setSpacing(18)
        frame, layout = card("应用使用时长", "最多展示使用时间最长的 7 个应用")
        self.bar = HorizontalBarChart()
        layout.addWidget(self.bar)
        top.addWidget(frame, 3)
        frame, layout = card("分类占比")
        self.donut = DonutChart()
        layout.addWidget(self.donut)
        self.categories = label("还没有分类数据", "muted", True)
        layout.addWidget(self.categories)
        top.addWidget(frame, 2)
        self.layout.addLayout(top)
        frame, layout = card("使用趋势")
        tools = QHBoxLayout()
        self.period = QComboBox()
        self.period.addItem("最近 7 天 · 周趋势", 7)
        self.period.addItem("最近 30 天 · 月趋势", 30)
        self.period.currentIndexChanged.connect(self.refresh)
        tools.addWidget(self.period)
        tools.addStretch()
        self.trend_total = label("", "muted")
        tools.addWidget(self.trend_total)
        layout.addLayout(tools)
        self.line = TrendChart()
        layout.addWidget(self.line)
        self.layout.addWidget(frame)
        frame, layout = card("历史记录日历", "有记录的日期会以粉色标出，选择日期查看当日数据。")
        self.calendar = QCalendarWidget()
        self.calendar.setGridVisible(False)
        self.calendar.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        self.calendar.clicked.connect(window.select_date)
        self.calendar.currentPageChanged.connect(self.mark_calendar)
        self.calendar.setMaximumWidth(540)
        layout.addWidget(self.calendar)
        self.layout.addWidget(frame)
        self.layout.addStretch()

    def mark_calendar(self, year: int | None = None, month: int | None = None) -> None:
        year = year or self.calendar.yearShown()
        month = month or self.calendar.monthShown()
        first = QDate(year, month, 1)
        last = QDate(year, month, first.daysInMonth())
        rows = self.repo.trend(last.toString("yyyy-MM-dd"), first.daysInMonth())
        # 清理上一次标记，数据库中删除某日后不会保留过时的颜色。
        self.calendar.setDateTextFormat(QDate(), QTextCharFormat())
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(colors(self.window.theme)["accent"]))
        fmt.setFontWeight(QFont.Weight.Bold)
        for row in rows:
            if float(row.get("seconds", 0)) > 0:
                self.calendar.setDateTextFormat(QDate.fromString(str(row["date"]), "yyyy-MM-dd"), fmt)

    def refresh(self) -> None:
        summary = self.repo.daily_summary(self.date)
        self.bar.set_data(summary.get("apps", []))
        self.donut.set_data(summary.get("categories", []))
        total = summary.get("total", 0)
        self.categories.setText("\n".join(f"{r['category']}  {r['seconds'] / total:.0%} · {duration_text(r['seconds'], compact=True)}" for r in summary.get("categories", [])) if total else "还没有分类数据")
        days = int(self.period.currentData())
        rows = self.repo.trend(self.date, days)
        self.line.set_data(rows)
        self.trend_total.setText(f"{days} 天合计 {duration_text(sum(float(r.get('seconds', 0)) for r in rows))}")
        with QSignalBlocker(self.calendar):
            self.calendar.setSelectedDate(self.window.selected_date)
        self.mark_calendar()


class DiaryPage(Page):
    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        self.loaded_date = ""
        self.dirty = False
        self.loading = False
        self.snapshot: dict = {}
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(650)
        self.timer.timeout.connect(self.flush)
        row = QHBoxLayout()
        row.setSpacing(18)
        frame, layout = card("生活也发生在屏幕之外", "日记自动保存到本机。手动记录不会增加电脑使用时长。")
        layout.addWidget(label("今天完成的事情", "subheading"))
        self.completed = QTextEdit()
        self.completed.setPlaceholderText("写下已经做过的事，一行一件也可以。")
        self.completed.setMinimumHeight(105)
        self.completed.setMaximumHeight(160)
        layout.addWidget(self.completed)
        mood_row = QHBoxLayout()
        mood_row.addWidget(label("今日心情", "subheading"))
        self.mood = QComboBox()
        self.mood.addItems(["未选择", "开心", "平静", "充实", "疲惫", "低落", "焦虑"])
        mood_row.addWidget(self.mood)
        mood_row.addStretch()
        layout.addLayout(mood_row)
        layout.addWidget(label("简短日记", "subheading"))
        self.body = QTextEdit()
        self.body.setPlaceholderText("今天有什么值得记住？")
        self.body.setMinimumHeight(215)
        layout.addWidget(self.body)
        self.tags = QLineEdit()
        self.tags.setPlaceholderText("标签，用逗号分隔，例如：运动，阅读")
        layout.addWidget(self.tags)
        self.saved = label("写下内容后会自动保存", "muted", True)
        layout.addWidget(self.saved)
        row.addWidget(frame, 3)
        side = QVBoxLayout()
        frame, layout = card("每日生活报告", "自动统计 + 手动记录，分别呈现")
        self.report = QTextEdit()
        self.report.setReadOnly(True)
        self.report.setMinimumHeight(260)
        layout.addWidget(self.report)
        layout.addWidget(button("复制报告", self.copy_report))
        side.addWidget(frame)
        frame, layout = card("翻看过去")
        self.calendar = QCalendarWidget()
        self.calendar.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        self.calendar.clicked.connect(window.select_date)
        layout.addWidget(self.calendar)
        side.addWidget(frame)
        side.addStretch()
        row.addLayout(side, 2)
        self.layout.addLayout(row)
        self.layout.addStretch()
        self.completed.textChanged.connect(self.changed)
        self.body.textChanged.connect(self.changed)
        self.tags.textChanged.connect(self.changed)
        self.mood.currentTextChanged.connect(self.changed)

    def changed(self, *args) -> None:
        if not self.loading:
            self.dirty = True
            self.saved.setText("正在等待保存…")
            self.timer.start()

    def flush(self) -> bool:
        self.timer.stop()
        if not self.dirty or not self.loaded_date:
            return True
        tags = [part.strip() for part in self.tags.text().replace("，", ",").split(",") if part.strip()]
        try:
            self.repo.save_diary(self.loaded_date, self.completed.toPlainText(), "" if self.mood.currentText() == "未选择" else self.mood.currentText(), self.body.toPlainText(), tags)
        except Exception as exc:
            self.saved.setText(f"保存失败：{exc}；你的内容仍保留在编辑器中。")
            return False
        self.dirty = False
        self.snapshot = self.repo.get_diary(self.loaded_date) or {}
        self.saved.setText("已保存到本机")
        self.update_report()
        return True

    def refresh(self) -> None:
        diary = self.repo.get_diary(self.date) or {}
        # 删除/恢复后会变化：干净的编辑器重新加载，不能把旧缓存写回已删除记录。
        if self.loaded_date != self.date or (not self.dirty and diary != self.snapshot):
            if not self.flush():
                return
            self.loading = True
            self.completed.setPlainText(str(diary.get("completed", "")))
            self.body.setPlainText(str(diary.get("body", "")))
            tags = diary.get("tags", [])
            self.tags.setText(", ".join(tags) if isinstance(tags, list) else str(tags))
            mood = str(diary.get("mood") or "未选择")
            self.mood.setCurrentText(mood if self.mood.findText(mood) >= 0 else "未选择")
            self.loaded_date = self.date
            self.snapshot = diary
            self.loading = False
            self.saved.setText("已载入本地日记" if any(diary.get(k) for k in ("completed", "body", "mood", "tags")) else "写下内容后会自动保存")
        with QSignalBlocker(self.calendar):
            self.calendar.setSelectedDate(self.window.selected_date)
        self.update_report()

    def update_report(self) -> None:
        if not self.loaded_date:
            return
        summary = self.repo.daily_summary(self.loaded_date)
        lines = [f"{self.loaded_date} · 每日生活报告", "", "自动记录 · 电脑使用", f"累计 {duration_text(summary.get('total', 0))}。"]
        apps = sorted(summary.get("apps", []), key=lambda r: r["seconds"], reverse=True)
        categories = sorted(summary.get("categories", []), key=lambda r: r["seconds"], reverse=True)
        if apps:
            lines.append(f"使用最多的是 {apps[0]['name']}，共 {duration_text(apps[0]['seconds'])}。")
        if categories:
            lines.append(f"时间主要用于{categories[0]['category']}。")
        if not apps:
            lines.append("这一天暂无电脑使用记录。")
        timeline = summary.get("timeline", [])
        if timeline:
            lines += ["", "自动时间轴："]
            for row in timeline:
                lines.append(f"{time_text(row.get('start'))}～{time_text(row.get('end'))}  {row.get('name', '未知应用')} · {duration_text(row.get('seconds', 0), compact=True)}")
        lines += ["", "手动记录 · 生活日记（不计入电脑时长）"]
        if self.mood.currentText() != "未选择":
            lines.append(f"心情：{self.mood.currentText()}")
        if self.completed.toPlainText().strip():
            lines.extend(["完成的事情：", self.completed.toPlainText().strip()])
        if self.body.toPlainText().strip():
            lines.extend(["日记：", self.body.toPlainText().strip()])
        if self.tags.text().strip():
            lines.append(f"标签：{self.tags.text().strip()}")
        if not any((self.completed.toPlainText().strip(), self.body.toPlainText().strip(), self.tags.text().strip(), self.mood.currentText() != "未选择")):
            lines.append("还没有手动生活记录。")
        self.report.setPlainText("\n".join(lines))

    def copy_report(self) -> None:
        self.flush()
        self.update_report()
        QApplication.clipboard().setText(self.report.toPlainText())
        self.saved.setText("报告已复制")


class EditAppDialog(QDialog):
    def __init__(self, row: dict, parent: QWidget) -> None:
        super().__init__(parent)
        self.row = row
        self.selected_icon: str | None = None
        self.setWindowTitle("编辑应用")
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.addWidget(label("让应用更好认", "heading"))
        form = QFormLayout()
        self.name = QLineEdit(str(row.get("name", "")))
        form.addRow("显示名称", self.name)
        self.category = QComboBox()
        self.category.addItems(CATEGORIES)
        self.category.setCurrentText(str(row.get("category", "其他")))
        form.addRow("应用分类", self.category)
        self.excluded = QCheckBox("排除该应用，之后不再记录它的使用历史")
        self.excluded.setChecked(bool(row.get("excluded", False)))
        form.addRow("统计规则", self.excluded)
        icon_row = QHBoxLayout()
        self.icon_label = label("自定义图标" if row.get("icon") else "默认程序图标", "muted")
        icon_row.addWidget(self.icon_label, 1)
        icon_row.addWidget(button("选择图标", self.choose_icon))
        icon_row.addWidget(button("重置", self.reset_icon))
        form.addRow("应用图标", icon_row)
        layout.addLayout(form)
        layout.addWidget(label(str(row.get("executable") or "无法读取程序路径"), "muted", True))
        layout.addWidget(label("修改分类和名称会同步更新历史展示；排除不会删除已有记录。", "muted", True))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def choose_icon(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(self, "选择应用图标", "", "图标文件 (*.png *.jpg *.jpeg *.ico *.svg)")
        if filename:
            icon = QIcon(filename)
            if icon.isNull():
                QMessageBox.warning(self, "无法读取图标", "请选择有效的图片或图标文件。")
                return
            self.selected_icon = filename
            self.icon_label.setText(Path(filename).name)

    def reset_icon(self) -> None:
        self.selected_icon = ""
        self.icon_label.setText("默认程序图标")

    def accept(self) -> None:
        if not self.name.text().strip():
            QMessageBox.warning(self, "名称不能为空", "请填写一个应用名称。")
            return
        super().accept()


class AppsPage(Page):
    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        self.apps: list[dict] = []
        frame, layout = card("把应用整理成你的日常", "应用在首次被统计时出现。DayTrace 自身默认排除。")
        tools = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索名称或程序路径")
        self.search.textChanged.connect(self.render_rows)
        tools.addWidget(self.search, 1)
        tools.addWidget(button("编辑所选应用", self.edit_selected, "primary"))
        layout.addLayout(tools)
        self.table = create_table(["应用", "分类", "是否统计", "程序路径"])
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.setMinimumHeight(400)
        self.table.itemDoubleClicked.connect(lambda _: self.edit_selected())
        layout.addWidget(self.table)
        self.empty = label("还没有已识别的应用。打开其他程序后，它们会自动出现在这里。", "muted", True)
        layout.addWidget(self.empty)
        self.layout.addWidget(frame)
        self.layout.addStretch()

    def refresh(self) -> None:
        selected = self.table.currentItem()
        selected_key = self.table.item(selected.row(), 0).data(Qt.ItemDataRole.UserRole) if selected else None
        self.apps = self.repo.list_apps()
        self.render_rows()
        if selected_key:
            for index in range(self.table.rowCount()):
                if self.table.item(index, 0).data(Qt.ItemDataRole.UserRole) == selected_key:
                    self.table.selectRow(index)
                    break

    def render_rows(self, *args) -> None:
        term = self.search.text().casefold().strip()
        rows = [r for r in self.apps if term in f"{r.get('name', '')} {r.get('executable', '')}".casefold()]
        self.table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            item = QTableWidgetItem(str(row.get("name", "未知应用")))
            item.setIcon(app_icon(row))
            item.setData(Qt.ItemDataRole.UserRole, row["key"])
            self.table.setItem(index, 0, item)
            for col, text in enumerate((row.get("category", "其他"), "已排除" if row.get("excluded") else "记录", row.get("executable") or "未知路径"), 1):
                cell = QTableWidgetItem(str(text))
                cell.setToolTip(str(text))
                self.table.setItem(index, col, cell)
        self.empty.setText("没有匹配的应用。" if self.apps else "还没有已识别的应用。打开其他程序后，它们会自动出现在这里。")
        self.empty.setVisible(not rows)

    def edit_selected(self) -> None:
        index = self.table.currentRow()
        if index < 0:
            QMessageBox.information(self, "选择应用", "先选择一个应用，再编辑名称、分类或排除规则。")
            return
        key = self.table.item(index, 0).data(Qt.ItemDataRole.UserRole)
        row = next(r for r in self.apps if r["key"] == key)
        dialog = EditAppDialog(row, self.window)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        icon_path = row.get("icon") or ""
        try:
            if dialog.selected_icon is not None:
                icon_path = dialog.selected_icon
                if icon_path:
                    database_path = Path(self.repo.path)
                    icon_dir = database_path.parent / "icons"
                    icon_dir.mkdir(parents=True, exist_ok=True)
                    destination = icon_dir / f"{uuid.uuid4().hex}{Path(icon_path).suffix.lower()}"
                    shutil.copy2(icon_path, destination)
                    icon_path = str(destination)
            self.repo.update_app(key, name=dialog.name.text().strip(), category=dialog.category.currentText(), excluded=dialog.excluded.isChecked(), icon=icon_path)
        except Exception as exc:
            QMessageBox.warning(self, "保存失败", str(exc))
            return
        self.window.invoke("apps_changed")
        self.refresh()


class SettingsPage(Page):
    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        frame, layout = card("记录方式", "只统计前台应用，不累计后台软件。")
        form = QFormLayout()
        form.setSpacing(14)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.mode = QComboBox()
        self.mode.addItem("前台模式 · 阅读 / 视频 / 游戏也会持续累计", "foreground")
        self.mode.addItem("活跃模式 · 超过空闲阈值后暂停累计", "active")
        self.mode.setMinimumWidth(260)
        self.mode.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        form.addRow("统计模式", self.mode)
        self.idle = QSpinBox()
        self.idle.setRange(1, 240)
        self.idle.setSuffix(" 分钟")
        form.addRow("活跃模式空闲阈值", self.idle)
        self.poll = QComboBox()
        self.poll.addItem("每 1 秒检测", 1.0)
        self.poll.addItem("每 2 秒检测（默认）", 2.0)
        form.addRow("前台检测频率", self.poll)
        layout.addLayout(form)
        layout.addWidget(label("两种模式都跳过锁屏、休眠、暂停及无法确认归属的时间。短于检测间隔的切换可能不会被观察到。", "muted", True))
        self.layout.addWidget(frame)
        frame, layout = card("桌面与每日回顾")
        form = QFormLayout()
        form.setSpacing(14)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.theme_choice = QComboBox()
        self.theme_choice.addItem("浅色 · 粉白与淡紫", "light")
        self.theme_choice.addItem("深色 · 柔和暮色", "dark")
        form.addRow("主题", self.theme_choice)
        self.autostart = QCheckBox("登录 Windows 后自动启动并留在托盘")
        form.addRow("开机自启动", self.autostart)
        reminder_row = QHBoxLayout()
        self.reminder = QCheckBox("启用每日回顾提醒")
        self.reminder_time = QTimeEdit()
        self.reminder_time.setDisplayFormat("HH:mm")
        reminder_row.addWidget(self.reminder)
        reminder_row.addWidget(self.reminder_time)
        reminder_row.addStretch()
        form.addRow("提醒", reminder_row)
        layout.addLayout(form)
        layout.addWidget(button("保存设置", self.save, "primary"))
        self.saved = label("", "muted", True)
        layout.addWidget(self.saved)
        self.layout.addWidget(frame)
        frame, layout = card("你的数据，只在本机", "数据不会上传。导出文件和备份包含你的使用历史及主动填写的生活记录。")
        tools = QHBoxLayout()
        tools.addWidget(button("导出 CSV", lambda: window.invoke("export", "csv")))
        tools.addWidget(button("导出 JSON", lambda: window.invoke("export", "json")))
        tools.addWidget(button("备份数据库", lambda: window.invoke("backup")))
        tools.addWidget(button("恢复数据库", self.restore))
        tools.addStretch()
        layout.addLayout(tools)
        self.data_path = label(str(getattr(self.repo, "path", "")), "muted", True)
        layout.addWidget(self.data_path)
        deletion = QHBoxLayout()
        self.delete_date = QDateEdit(window.selected_date)
        self.delete_date.setCalendarPopup(True)
        self.delete_date.setDisplayFormat("yyyy-MM-dd")
        deletion.addWidget(self.delete_date)
        deletion.addWidget(button("删除指定日期", self.delete_day, "danger"))
        deletion.addStretch()
        deletion.addWidget(button("清空全部历史", self.clear_history, "danger"))
        layout.addLayout(deletion)
        self.layout.addWidget(frame)
        self.layout.addStretch()
        self.load()
        self.mode.currentIndexChanged.connect(lambda: self.idle.setEnabled(self.mode.currentData() == "active"))

    def load(self) -> None:
        def choose(combo: QComboBox, value) -> None:
            index = combo.findData(value)
            combo.setCurrentIndex(index if index >= 0 else 0)
        choose(self.mode, self.repo.get_setting("mode", "foreground"))
        self.idle.setValue(max(1, round(float(self.repo.get_setting("idle_threshold_seconds", 300)) / 60)))
        self.idle.setEnabled(self.mode.currentData() == "active")
        choose(self.poll, float(self.repo.get_setting("poll_interval_seconds", 2)))
        choose(self.theme_choice, self.repo.get_setting("theme", "light"))
        self.autostart.setChecked(bool(self.repo.get_setting("autostart", False)))
        self.reminder.setChecked(bool(self.repo.get_setting("reminder_enabled", False)))
        time = QTime.fromString(str(self.repo.get_setting("reminder_time", "21:30")), "HH:mm")
        self.reminder_time.setTime(time if time.isValid() else QTime(21, 30))

    def save(self) -> None:
        settings = {
            "mode": self.mode.currentData(), "idle_threshold_seconds": self.idle.value() * 60,
            "poll_interval_seconds": self.poll.currentData(), "theme": self.theme_choice.currentData(),
            "autostart": self.autostart.isChecked(), "reminder_enabled": self.reminder.isChecked(),
            "reminder_time": self.reminder_time.time().toString("HH:mm"),
        }
        try:
            # 根控制器负责验证、切换统计服务及自启动，完成后才显示成功。
            if "settings_changed" in self.window.actions:
                self.window.actions["settings_changed"](settings)
            else:
                for key, value in settings.items():
                    self.repo.set_setting(key, value)
            self.window.theme = str(settings["theme"])
            apply_theme(self.window, self.window.theme)
            self.window.sync_mode_selector()
            self.saved.setText("设置已保存并生效。")
        except Exception as exc:
            self.saved.setText(f"保存失败：{exc}")

    def restore(self) -> None:
        # 控制器在选定具体备份后提供替换确认，避免连续重复确认。
        if self.window.flush_diary():
            self.window.invoke("restore")

    def delete_day(self) -> None:
        date = self.delete_date.date().toString("yyyy-MM-dd")
        if QMessageBox.question(self, "删除指定日期", f"删除 {date} 的软件使用历史及生活日记？此操作无法撤销。", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            if self.window.flush_diary():
                self.window.invoke("delete_date", date)

    def clear_history(self) -> None:
        if QMessageBox.question(self, "清空全部历史", "清空所有日期的软件使用历史及生活日记？应用设置会保留。此操作无法撤销，建议先备份。", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            if self.window.flush_diary():
                self.window.invoke("clear_history")


class MainWindow(QMainWindow):
    """外部控制器通过 actions 接入服务、托盘和文件操作。"""
    PAGE_NAMES = ["今日概览", "时间轴", "统计分析", "生活日记", "应用管理", "设置"]
    PAGE_TYPES = [OverviewPage, TimelinePage, AnalyticsPage, DiaryPage, AppsPage, SettingsPage]

    def __init__(self, repository, actions: dict[str, Callable] | None = None) -> None:
        super().__init__()
        self.repository = repository
        self.actions = actions or {}
        self.tray_available = False
        self.allow_close = False
        self.paused = False
        self.theme = str(repository.get_setting("theme", "light"))
        self.selected_date = QDate.currentDate()
        self.current_page = 0
        self.pages: dict[int, Page] = {}
        self.setWindowTitle("DayTrace · 让每一天有迹可循")
        self.resize(1180, 820)
        self.setMinimumSize(900, 640)
        self.artwork = Artwork()
        shell = SceneryShell(self.artwork)
        self.setCentralWidget(shell)
        layout = QHBoxLayout(shell)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        sidebar = ScenerySidebar()
        self.sidebar = sidebar
        sidebar.setFixedWidth(204)
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(12, 21, 12, 19)
        side_layout.setSpacing(4)
        brand = QHBoxLayout()
        brand.setSpacing(9)
        brand.addWidget(BrandMark())
        brand_text = QVBoxLayout()
        brand_text.setSpacing(0)
        logo = label("DayTrace")
        logo.setStyleSheet("font-family: 'Georgia', 'Times New Roman', 'Microsoft YaHei UI'; font-size: 25px; font-weight: 600;")
        brand_text.addWidget(logo)
        brand_text.addWidget(label("日常，慢慢记下来", "muted"))
        brand.addLayout(brand_text)
        side_layout.addLayout(brand)
        side_layout.addSpacing(20)
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav: list[QPushButton] = []
        for index, title in enumerate(self.PAGE_NAMES):
            nav = button(f"  {title}", lambda checked=False, i=index: self.show_page(i), "nav")
            sticker_button(nav, self.artwork, index, size=48, fallback=navigation_icon(index))
            nav.setObjectName(f"nav_{index}")
            nav.setFixedHeight(68)
            nav.setCheckable(True)
            self.nav_group.addButton(nav, index)
            self.nav.append(nav)
            side_layout.addWidget(nav)
        side_layout.addStretch()
        side_layout.addWidget(label("仅在本机保存", "eyebrow"))
        side_layout.addWidget(label("前台使用 · 生活日记\n不记录内容，不上传数据", "muted", True))
        layout.addWidget(sidebar)
        content = QVBoxLayout()
        content.setContentsMargins(24, 20, 24, 18)
        content.setSpacing(13)
        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(4)
        self.title = label(self.PAGE_NAMES[0], "heading")
        self.subtitle = label("看见时间，也记住生活。", "muted")
        titles.addWidget(self.title)
        titles.addWidget(self.subtitle)
        header.addLayout(titles, 1)
        self.status = label("正在准备统计", None)
        self.status.setObjectName("Status")
        self.status.setMaximumWidth(182)
        header.addWidget(self.status)
        self.mode_selector = QComboBox()
        self.mode_selector.setObjectName("mode_selector")
        self.mode_selector.addItem("前台模式", "foreground")
        self.mode_selector.addItem("活跃模式", "active")
        self.mode_selector.setFixedWidth(115)
        self.sync_mode_selector()
        self.mode_selector.currentIndexChanged.connect(self.change_mode)
        header.addWidget(self.mode_selector)
        self.pause_button = sticker_button(button("暂停统计", self.toggle_pause), self.artwork, 9, size=33, fallback=navigation_icon(0))
        self.pause_button.setObjectName("tracking_pause")
        header.addWidget(self.pause_button)
        content.addLayout(header)
        date_row = QHBoxLayout()
        self.date_widget = QWidget()
        date_layout = QHBoxLayout(self.date_widget)
        date_layout.setContentsMargins(0, 0, 0, 0)
        date_layout.setSpacing(8)
        self.previous_button = sticker_button(button("上一天", lambda: self.select_date(self.selected_date.addDays(-1))), self.artwork, 6, size=32, fallback=navigation_icon(1))
        self.previous_button.setObjectName("date_previous")
        date_layout.addWidget(self.previous_button)
        self.date_edit = QDateEdit(self.selected_date)
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy 年 MM 月 dd 日")
        self.date_edit.setFixedWidth(183)
        self.date_edit.dateChanged.connect(self.select_date)
        date_layout.addWidget(self.date_edit)
        self.next_button = sticker_button(button("下一天", lambda: self.select_date(self.selected_date.addDays(1))), self.artwork, 7, size=32, fallback=navigation_icon(1))
        self.next_button.setObjectName("date_next")
        self.today_button = sticker_button(button("今天", lambda: self.select_date(QDate.currentDate())), self.artwork, 8, size=32, fallback=navigation_icon(0))
        self.today_button.setObjectName("date_today")
        date_layout.addWidget(self.next_button)
        date_layout.addWidget(self.today_button)
        date_row.addWidget(self.date_widget)
        date_row.addStretch()
        self.day_note = label("", "muted")
        date_row.addWidget(self.day_note)
        content.addLayout(date_row)
        self.stack = QStackedWidget()
        self.placeholders = []
        for _ in self.PAGE_NAMES:
            placeholder = QWidget()
            self.placeholders.append(placeholder)
            self.stack.addWidget(placeholder)
        content.addWidget(self.stack, 1)
        layout.addLayout(content, 1)
        apply_theme(self, self.theme)
        self.show_page(0)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "nav"):
            short = self.height() < 735
            for nav in self.nav:
                nav.setFixedHeight(54 if short else 68)
                nav.setIconSize(QSize(39, 39) if short else QSize(48, 48))
        if hasattr(self, "status"):
            self.status.setMaximumWidth(145 if self.width() < 1050 else 182)

    def sync_mode_selector(self) -> None:
        mode = self.repository.get_setting("mode", "foreground")
        with QSignalBlocker(self.mode_selector):
            index = self.mode_selector.findData(mode)
            self.mode_selector.setCurrentIndex(max(0, index))

    def change_mode(self, index: int) -> None:
        mode = self.mode_selector.itemData(index)
        previous = self.repository.get_setting("mode", "foreground")
        if mode == previous:
            return
        if "settings_changed" not in self.actions:
            self.sync_mode_selector()
            self.mode_selector.setToolTip("请通过设置页面保存统计模式。")
            return
        self.invoke("settings_changed", {"mode": mode})
        # invoke 会提示控制器异常；只有数据库确认成功后，UI 才保留新选项。
        self.sync_mode_selector()
        applied = self.repository.get_setting("mode", "foreground") == mode
        self.mode_selector.setToolTip("模式已切换" if applied else "切换未完成，保留原模式")
        if applied and 5 in self.pages:
            page = self.pages[5]
            with QSignalBlocker(page.mode):
                page.mode.setCurrentIndex(page.mode.findData(mode))
            page.idle.setEnabled(mode == "active")
        if self.current_page == 0:
            self.pages[0].refresh()

    def invoke(self, name: str, *args):
        callback = self.actions.get(name)
        if callback:
            try:
                return callback(*args)
            except Exception as exc:
                QMessageBox.warning(self, "操作未完成", str(exc))
        return None

    def show_page(self, index: int) -> None:
        if index not in range(len(self.PAGE_NAMES)):
            return
        if self.current_page in self.pages:
            if self.pages[self.current_page].flush() is False:
                return
        self.current_page = index
        if index not in self.pages:
            page = self.PAGE_TYPES[index](self)
            self.pages[index] = page
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setWidget(page)
            self.stack.removeWidget(self.placeholders[index])
            self.placeholders[index].deleteLater()
            self.stack.insertWidget(index, scroll)
            apply_theme(self, self.theme)
        self.stack.setCurrentIndex(index)
        self.nav[index].setChecked(True)
        self.title.setText(self.PAGE_NAMES[index])
        subtitles = ["看见时间，也记住生活。", "一天的应用切换，都有迹可循。", "从真实记录里，了解自己的节奏。", "不在电脑上的生活，也值得记下来。", "按自己的习惯，整理应用与分类。", "按你的方式记录，数据留在本机。"]
        self.subtitle.setText(subtitles[index])
        self.date_widget.setVisible(index < 4)
        self.day_note.setVisible(index < 4)
        self.day_note.setText("今天" if self.selected_date == QDate.currentDate() else self.selected_date.toString("dddd"))
        self.pages[index].refresh()

    def select_date(self, date: QDate | str) -> None:
        if isinstance(date, str):
            date = QDate.fromString(date, "yyyy-MM-dd")
        if not date.isValid():
            return
        if not self.flush_diary():
            with QSignalBlocker(self.date_edit):
                self.date_edit.setDate(self.selected_date)
            return
        self.selected_date = date
        with QSignalBlocker(self.date_edit):
            self.date_edit.setDate(date)
        self.day_note.setText("今天" if date == QDate.currentDate() else date.toString("dddd"))
        if self.current_page in self.pages:
            self.pages[self.current_page].refresh()

    def flush_diary(self) -> bool:
        if 3 in self.pages:
            return self.pages[3].flush()
        return True

    def refresh(self) -> None:
        # 关闭到托盘后不查询报表，不重绘图表；采集服务独立运行。
        if self.isVisible() and self.current_page in self.pages:
            try:
                self.sync_mode_selector()
                self.pages[self.current_page].refresh()
            except Exception as exc:
                self.status.setText(f"加载失败：{exc}")

    def invalidate_diary(self) -> None:
        """删除/恢复数据库后，让下次访问从真实数据库重新载入。"""
        if 3 in self.pages:
            page = self.pages[3]
            page.timer.stop()
            page.dirty = False
            page.loaded_date = ""
            page.snapshot = {}

    def reload_after_restore(self) -> None:
        """恢复成功后丢弃旧缓存，重新载入设置与日记；此处绝不保存旧日记。"""
        self.invalidate_diary()
        self.theme = str(self.repository.get_setting("theme", "light"))
        if 5 in self.pages:
            self.pages[5].load()
        self.sync_mode_selector()
        apply_theme(self, self.theme)
        self.refresh()

    def set_tracking_status(self, status: str, paused: bool) -> None:
        self.paused = bool(paused)
        self.status.setToolTip(status)
        self.status.setText(self.status.fontMetrics().elidedText(status, Qt.TextElideMode.ElideRight, self.status.maximumWidth() - 22))
        self.pause_button.setText("恢复统计" if paused else "暂停统计")
        self.pause_button.setAccessibleName(self.pause_button.text())

    def toggle_pause(self) -> None:
        self.invoke("pause", not self.paused)

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self.flush_diary():
            event.ignore()
            return
        if self.allow_close:
            event.accept()
        elif self.tray_available:
            event.ignore()
            self.hide()
        else:
            answer = QMessageBox.question(self, "退出 DayTrace", "系统托盘当前不可用。完全退出后会停止统计，确定退出？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer == QMessageBox.StandardButton.Yes:
                self.allow_close = True
                event.accept()
                self.invoke("quit")
                if "quit" not in self.actions:
                    QApplication.instance().quit()
            else:
                event.ignore()
