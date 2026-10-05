"""轻量原生 QPainter 图表，只在窗口要求重绘时绘制。"""
from __future__ import annotations

from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from .theme import colors, category_color


def duration_text(seconds: float, *, compact: bool = False) -> str:
    seconds = max(0, int(seconds or 0))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if compact:
        if hours:
            return f"{hours}h {minutes:02d}m"
        return f"{minutes}m" if minutes else f"{seconds}s"
    if hours:
        return f"{hours} 小时 {minutes} 分钟"
    if minutes:
        return f"{minutes} 分钟 {seconds} 秒"
    return f"{seconds} 秒"


class Chart(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.theme = "light"
        self.setMinimumHeight(190)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)

    def set_theme(self, theme: str) -> None:
        self.theme = theme
        self.update()

    def empty(self, painter: QPainter, note: str = "这一天还没有使用记录") -> None:
        c = colors(self.theme)
        painter.setPen(QColor(c["muted"]))
        painter.setFont(QFont("Microsoft YaHei UI", 10))
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, note)


class DonutChart(Chart):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.data: list[dict] = []
        self.setMinimumHeight(208)

    def set_data(self, categories: list[dict]) -> None:
        self.data = [dict(row) for row in categories if float(row.get("seconds", 0)) > 0]
        self.setToolTip("\n".join(f"{r['category']}：{duration_text(r['seconds'])}" for r in self.data))
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = colors(self.theme)
        size = max(70.0, min(self.width() - 28, self.height() - 24, 214))
        rect = QRectF((self.width() - size) / 2, (self.height() - size) / 2, size, size)
        width = max(13, size * .1)
        ring = rect.adjusted(width / 2, width / 2, -width / 2, -width / 2)
        painter.setPen(QPen(QColor(c["border"]), width))
        painter.drawEllipse(ring)
        total = sum(float(row["seconds"]) for row in self.data)
        if total:
            start = 90 * 16
            for row in self.data:
                span = float(row["seconds"]) / total * 360 * 16
                painter.setPen(QPen(category_color(row["category"]), width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
                painter.drawArc(ring, round(start), -round(span))
                start -= span
        painter.setPen(QColor(c["text"]))
        center_text = duration_text(total, compact=True)
        center_font = QFont("Segoe UI", 20, QFont.Weight.DemiBold)
        # 小尺寸环形图也要容纳较长时长，不让中心文字压到彩色圆环上。
        inner_width = max(24, size - width * 2 - 12)
        measured_width = QFontMetricsF(center_font).horizontalAdvance(center_text)
        if measured_width > inner_width:
            center_font.setPointSizeF(max(9, 20 * inner_width / measured_width))
        painter.setFont(center_font)
        painter.drawText(rect.adjusted(width + 6, -8, -width - 6, -8), Qt.AlignmentFlag.AlignCenter, center_text)
        painter.setFont(QFont("Microsoft YaHei UI", 9))
        painter.setPen(QColor(c["muted"]))
        painter.drawText(QRectF(rect.left(), rect.center().y() + 17, size, 26), Qt.AlignmentFlag.AlignCenter, "电脑使用" if total else "等待第一条记录")


class HorizontalBarChart(Chart):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.data: list[dict] = []
        self.setMinimumHeight(220)

    def set_data(self, applications: list[dict]) -> None:
        self.data = sorted((dict(row) for row in applications if float(row.get("seconds", 0)) > 0), key=lambda r: r["seconds"], reverse=True)[:7]
        self.setMinimumHeight(max(200, len(self.data) * 44 + 10))
        self.setToolTip("\n".join(f"{r['name']}：{duration_text(r['seconds'])}" for r in self.data))
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.data:
            self.empty(painter)
            return
        c = colors(self.theme)
        largest = max(float(row["seconds"]) for row in self.data)
        left = min(133, max(90, self.width() * .26))
        right = 86
        available = max(40, self.width() - left - right - 12)
        height = min(46, (self.height() - 14) / len(self.data))
        painter.setFont(QFont("Microsoft YaHei UI", 9))
        for index, row in enumerate(self.data):
            y = 6 + index * height
            label = painter.fontMetrics().elidedText(str(row["name"]), Qt.TextElideMode.ElideRight, int(left - 15))
            painter.setPen(QColor(c["text"]))
            painter.drawText(QRectF(0, y, left - 12, height), Qt.AlignmentFlag.AlignVCenter, label)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(c["hover"]))
            painter.drawRoundedRect(QRectF(left, y + height * .32, available, height * .32), 5, 5)
            painter.setBrush(category_color(row.get("category", "其他")))
            painter.drawRoundedRect(QRectF(left, y + height * .32, max(2, available * row["seconds"] / largest), height * .32), 5, 5)
            painter.setPen(QColor(c["muted"]))
            painter.drawText(QRectF(left + available + 10, y, right, height), Qt.AlignmentFlag.AlignVCenter, duration_text(row["seconds"], compact=True))


class TrendChart(Chart):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.data: list[dict] = []
        self.setMinimumHeight(230)

    def set_data(self, trend: list[dict]) -> None:
        self.data = [dict(row) for row in trend]
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.data or not any(float(row.get("seconds", 0)) > 0 for row in self.data):
            self.empty(painter, "这个时间段还没有使用记录")
            return
        c = colors(self.theme)
        graph = QRectF(43, 18, max(40, self.width() - 60), max(40, self.height() - 55))
        maximum = max(float(row["seconds"]) for row in self.data)
        maximum = max(3600, int(maximum / 3600 + .999) * 3600)
        painter.setFont(QFont("Segoe UI", 9))
        for i in range(4):
            y = graph.bottom() - graph.height() * i / 3
            painter.setPen(QPen(QColor(c["border"]), 1, Qt.PenStyle.DotLine))
            painter.drawLine(QPointF(graph.left(), y), QPointF(graph.right(), y))
            painter.setPen(QColor(c["muted"]))
            hours = maximum * i / 10800
            value = f"{hours:.1f}".rstrip("0").rstrip(".") if hours else "0"
            painter.drawText(QRectF(0, y - 10, 35, 20), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"{value}h")
        points = [QPointF(graph.left() + graph.width() * i / max(1, len(self.data) - 1), graph.bottom() - graph.height() * float(row["seconds"]) / maximum) for i, row in enumerate(self.data)]
        path = QPainterPath(points[0])
        for point in points[1:]:
            path.lineTo(point)
        fill = QPainterPath(path)
        fill.lineTo(graph.right(), graph.bottom())
        fill.lineTo(graph.left(), graph.bottom())
        fill.closeSubpath()
        shade = QColor(c["accent"])
        shade.setAlpha(27)
        painter.fillPath(fill, shade)
        painter.setPen(QPen(QColor(c["accent"]), 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.drawPath(path)
        painter.setBrush(QColor(c["surface"]))
        if len(points) <= 7:
            for point in points:
                painter.drawEllipse(point, 3.5, 3.5)
        painter.setPen(QColor(c["muted"]))
        indices = range(len(points)) if len(points) <= 7 else [0, len(points) // 4, len(points) // 2, len(points) * 3 // 4, len(points) - 1]
        for index in indices:
            label = str(self.data[index]["date"])[5:].replace("-", "/")
            painter.drawText(QRectF(points[index].x() - 28, graph.bottom() + 9, 56, 25), Qt.AlignmentFlag.AlignCenter, label)
