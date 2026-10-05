"""DayTrace 原生 Qt 主题；不依赖浏览器或网络字体。"""
from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication, QWidget


LIGHT = {
    "background": "#fff8f5", "surface": "#fffdfc", "sidebar": "#fff5f5",
    "text": "#392647", "muted": "#92829c", "border": "#efdcdf",
    "accent": "#bf5b8d", "accent_soft": "#fce3ed", "hover": "#fff0f4",
    "lavender": "#eee6fd", "success": "#45836b", "field": "#fffcfe",
}
DARK = {
    "background": "#211e27", "surface": "#2c2733", "sidebar": "#27212d",
    "text": "#f5eaf2", "muted": "#b9aaba", "border": "#433747",
    "accent": "#ee96b6", "accent_soft": "#503043", "hover": "#382d40",
    "lavender": "#383149", "success": "#97cdb5", "field": "#28232f",
}
CATEGORY_COLORS = {
    "学习与编程": "#e994bd", "游戏娱乐": "#d988ad", "社交聊天": "#89bdaa",
    "视频与音乐": "#eac27d", "工作办公": "#bca6e6", "系统工具": "#a8b5c8",
    "其他": "#c7a8bc",
}
CATEGORIES = list(CATEGORY_COLORS)


def colors(theme: str = "light") -> dict[str, str]:
    return DARK if theme == "dark" else LIGHT


def category_color(category: str) -> QColor:
    return QColor(CATEGORY_COLORS.get(category, "#c7a8bc"))


def apply_theme(widget: QWidget, theme: str) -> None:
    """只更新配色和样式；图表没有后台动画或持续渲染循环。"""
    theme = "dark" if theme == "dark" else "light"
    widget.setProperty("daytraceTheme", theme)
    c = colors(theme)
    surface = "rgba(44,39,51,238)" if theme == "dark" else "rgba(255,253,252,230)"
    sidebar = "rgba(39,33,45,235)" if theme == "dark" else "rgba(255,246,246,222)"
    app = QApplication.instance()
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(c["background"]))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(c["text"]))
    palette.setColor(QPalette.ColorRole.Base, QColor(c["field"]))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(c["hover"]))
    palette.setColor(QPalette.ColorRole.Text, QColor(c["text"]))
    palette.setColor(QPalette.ColorRole.Button, QColor(c["surface"]))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(c["text"]))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(c["accent"]))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(c["surface"]))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(c["muted"]))
    if app:
        app.setPalette(palette)
        app.setFont(QFont("Microsoft YaHei UI", 10))
    widget.setPalette(palette)
    widget.setStyleSheet(f"""
        QMainWindow {{ background: {c['background']}; }}
        QWidget#Shell, QWidget#Page, QStackedWidget {{ background: transparent; }}
        QWidget {{ color: {c['text']}; font-family: 'Microsoft YaHei UI', 'Segoe UI'; font-size: 13px; }}
        QFrame#Sidebar {{ background: {sidebar}; border-right: 1px solid {c['border']}; }}
        QFrame#Card {{ background: {surface}; border: 1px solid {c['border']}; border-radius: 16px; }}
        QFrame#Hero {{ background: {c['accent_soft']}; border: 1px solid {c['border']}; border-radius: 18px; }}
        QFrame#IllustratedHero {{ background: transparent; }}
        QFrame#TopApp {{ background: {surface}; border: 1px solid {c['border']}; border-radius: 12px; }}
        QLabel {{ background: transparent; }}
        QLabel[role='muted'] {{ color: {c['muted']}; }}
        QLabel[role='eyebrow'] {{ color: {c['accent']}; font-size: 11px; font-weight: 600; letter-spacing: 1px; }}
        QLabel[role='heading'] {{ font-family: 'SimSun', 'Songti SC', 'Microsoft YaHei UI'; font-size: 30px; font-weight: 600; }}
        QLabel[role='subheading'] {{ font-family: 'SimSun', 'Microsoft YaHei UI'; font-size: 18px; font-weight: 600; }}
        QLabel[role='metric'] {{ font-family: 'Segoe UI', 'Microsoft YaHei UI'; font-size: 36px; font-weight: 600; }}
        QLabel#OverviewTotal {{ color: {c['accent']}; font-family: 'SimSun', 'Microsoft YaHei UI'; font-size: 43px; font-weight: 600; }}
        QLabel#AutoBadge {{ color: {c['accent']}; background: {c['accent_soft']}; border-radius: 10px; padding: 5px 11px; }}
        QLabel#ManualBadge {{ color: {c['text']}; background: {c['lavender']}; border-radius: 10px; padding: 4px 9px; font-size: 11px; }}
        QLabel#DiaryPreview {{ background: {c['field']}; border: 1px solid {c['border']}; border-radius: 11px; padding: 12px; }}
        QLabel#Status {{ color: {c['success']}; background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 12px; padding: 7px 12px; }}
        QPushButton {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 9px; padding: 8px 13px; min-height: 19px; }}
        QPushButton:hover {{ background: {c['hover']}; border-color: {c['accent']}; }}
        QPushButton:pressed {{ background: {c['accent_soft']}; }}
        QPushButton:disabled {{ color: {c['muted']}; }}
        QPushButton[role='primary'] {{ background: {c['accent']}; color: {c['surface']}; border-color: {c['accent']}; font-weight: 600; }}
        QPushButton[role='danger'] {{ color: {c['accent']}; }}
        QPushButton[role='nav'] {{ background: transparent; border: none; text-align: left; padding: 5px 10px; font-size: 15px; border-radius: 12px; }}
        QPushButton[role='nav']:hover {{ background: {c['hover']}; }}
        QPushButton[role='nav']:checked {{ background: {c['accent_soft']}; color: {c['accent']}; border-left: 3px solid {c['accent']}; font-weight: 600; }}
        QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QDateEdit, QTimeEdit, QSpinBox {{ background: {c['field']}; border: 1px solid {c['border']}; border-radius: 8px; padding: 8px; selection-background-color: {c['accent_soft']}; selection-color: {c['text']}; }}
        QTextEdit:focus, QPlainTextEdit:focus, QLineEdit:focus {{ border-color: {c['accent']}; }}
        QComboBox::drop-down, QDateEdit::drop-down, QTimeEdit::drop-down {{ border: none; width: 22px; }}
        QComboBox QAbstractItemView {{ background: {c['surface']}; selection-background-color: {c['accent_soft']}; selection-color: {c['text']}; border: 1px solid {c['border']}; }}
        QCheckBox {{ spacing: 9px; }}
        QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid {c['border']}; border-radius: 4px; background: {c['field']}; }}
        QCheckBox::indicator:checked {{ background: {c['accent']}; border-color: {c['accent']}; }}
        QTableWidget {{ background: {c['surface']}; border: none; gridline-color: {c['border']}; selection-background-color: {c['accent_soft']}; selection-color: {c['text']}; alternate-background-color: {c['hover']}; }}
        QTableWidget::item {{ padding: 8px; border-bottom: 1px solid {c['border']}; }}
        QHeaderView::section {{ color: {c['muted']}; background: {c['surface']}; border: none; border-bottom: 1px solid {c['border']}; padding: 10px 8px; font-weight: 400; }}
        QScrollArea {{ border: none; background: transparent; }}
        QScrollArea > QWidget > QWidget {{ background: transparent; }}
        QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
        QScrollBar::handle:vertical {{ background: {c['border']}; border-radius: 3px; min-height: 26px; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
        QCalendarWidget {{ background: {c['surface']}; }}
        QCalendarWidget QAbstractItemView {{ background: {c['surface']}; selection-background-color: {c['accent']}; selection-color: {c['surface']}; border: none; }}
        QCalendarWidget QToolButton {{ color: {c['text']}; background: {c['surface']}; border: none; padding: 5px; }}
        QCalendarWidget QWidget#qt_calendar_navigationbar {{ background: {c['surface']}; }}
        QToolTip {{ background: {c['surface']}; color: {c['text']}; border: 1px solid {c['border']}; padding: 6px; }}
        QDialog {{ background: {c['background']}; }}
        QMenu {{ background: {c['surface']}; color: {c['text']}; border: 1px solid {c['border']}; padding: 6px; }}
        QMenu::item {{ padding: 7px 18px; }}
        QMenu::item:selected {{ background: {c['accent_soft']}; }}
    """)
    for child in widget.findChildren(QWidget):
        if hasattr(child, "set_theme"):
            child.set_theme(theme)

