"""静态本地美术与图集。Qt 运行时按格裁切，不播放视频，不联网。"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QImageReader, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QFrame, QPushButton, QWidget

from .theme import colors


def art_directory() -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return root / "assets" / "art"


def _read_image(path: Path, limit: QSize) -> QPixmap:
    """在解码时限制静态素材尺寸，避免把壁纸原图全尺寸长期留在内存。"""
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    size = reader.size()
    if size.isValid() and (size.width() > limit.width() or size.height() > limit.height()):
        reader.setScaledSize(size.scaled(limit, Qt.AspectRatioMode.KeepAspectRatio))
    image = reader.read()
    return QPixmap.fromImage(image) if not image.isNull() else QPixmap()


class Artwork:
    """每个窗口共享同一套图片；缩放结果只保留当前尺寸。"""
    def __init__(self) -> None:
        directory = art_directory()
        self.main = QPixmap()
        for path in sorted(directory.glob("main-art.*")):
            self.main = _read_image(path, QSize(1600, 1000))
            if not self.main.isNull():
                break
        self.backdrop = _read_image(directory / "backdrop.png", QSize(1200, 800))
        sheet = _read_image(directory / "stickers.png", QSize(1536, 1536))
        self.stickers: list[QIcon] = []
        if not sheet.isNull() and sheet.width() >= 4 and sheet.height() >= 3:
            cell_width, cell_height = sheet.width() // 4, sheet.height() // 3
            for index in range(12):
                cell = sheet.copy((index % 4) * cell_width, (index // 4) * cell_height, cell_width, cell_height)
                # 操作图标最高约 72 物理像素（150% DPI），128 像素足够并释放大格子。
                self.stickers.append(QIcon(cell.scaled(128, 128, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)))

    def icon(self, index: int, fallback: QIcon | None = None) -> QIcon:
        if index < len(self.stickers):
            return self.stickers[index]
        return fallback or QIcon()


def sticker_button(button: QPushButton, artwork: Artwork, index: int, *, size: int = 36, fallback: QIcon | None = None) -> QPushButton:
    button.setProperty("stickerIndex", index)
    button.setIcon(artwork.icon(index, fallback))
    button.setIconSize(QSize(size, size))
    button.setAccessibleName(button.text().strip())
    return button


def butterfly(painter: QPainter, x: float, y: float, size: float, color: QColor, angle: float = -20) -> None:
    painter.save()
    painter.translate(x, y)
    painter.rotate(angle)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    for direction in (-1, 1):
        path = QPainterPath(QPointF(0, 0))
        path.cubicTo(direction * size * .85, -size * .8, direction * size * 1.05, -size * .1, direction * size * .13, size * .12)
        path.cubicTo(direction * size * .7, size * .1, direction * size * .55, size * .6, 0, size * .22)
        painter.drawPath(path)
    painter.setPen(QPen(color.darker(110), max(1, size * .07), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.drawLine(QPointF(0, -size * .18), QPointF(0, size * .28))
    painter.restore()


def blossoms(painter: QPainter, x: float, y: float, scale: float, dark: bool = False) -> None:
    painter.save()
    painter.translate(x, y)
    painter.setPen(QPen(QColor("#89716c" if dark else "#cbb4a0"), 1.2))
    painter.drawLine(QPointF(-18 * scale, 30 * scale), QPointF(17 * scale, -19 * scale))
    for px, py, radius in ((-14, 19, 6), (1, 2, 8), (13, -16, 6)):
        painter.save()
        painter.translate(px * scale, py * scale)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#85576c" if dark else "#f5bfd1"))
        for angle in range(0, 360, 72):
            painter.rotate(72)
            painter.drawEllipse(QRectF(-radius * scale * .55, -radius * scale * 1.35, radius * scale * 1.1, radius * scale * 1.6))
        painter.setBrush(QColor("#d5b27e" if dark else "#f2d495"))
        painter.drawEllipse(QPointF(0, 0), 2 * scale, 2 * scale)
        painter.restore()
    painter.restore()


class SceneryShell(QWidget):
    def __init__(self, artwork: Artwork) -> None:
        super().__init__()
        self.artwork = artwork
        self.theme = "light"
        self._scaled = QPixmap()
        self._scaled_size = QSize()
        self._scaled_dpr = 0.0
        self.setObjectName("Shell")

    def set_theme(self, theme: str) -> None:
        self.theme = theme
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(colors(self.theme)["background"]))
        if not self.artwork.backdrop.isNull():
            dpr = self.devicePixelRatioF()
            if self._scaled_size != self.size() or self._scaled_dpr != dpr:
                physical_size = QSize(round(self.width() * dpr), round(self.height() * dpr))
                self._scaled = self.artwork.backdrop.scaled(physical_size, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
                self._scaled.setDevicePixelRatio(dpr)
                self._scaled_size = self.size()
                self._scaled_dpr = dpr
            painter.setOpacity(.10 if self.theme == "dark" else .21)
            logical = self._scaled.deviceIndependentSize()
            painter.drawPixmap(round((self.width() - logical.width()) / 2), round((self.height() - logical.height()) / 2), self._scaled)
            painter.setOpacity(1)
        blossoms(painter, 215, 28, 1.25, self.theme == "dark")
        blossoms(painter, self.width() - 12, self.height() - 28, 1.6, self.theme == "dark")
        butterfly(painter, self.width() - 75, 29, 11, QColor("#957cbd" if self.theme == "dark" else "#c3ace9"))


class ScenerySidebar(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.theme = "light"
        self.setObjectName("Sidebar")

    def set_theme(self, theme: str) -> None:
        self.theme = theme
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setOpacity(.55)
        blossoms(painter, 17, self.height() - 88, 2.2, self.theme == "dark")
        blossoms(painter, self.width() - 13, 22, 1.3, self.theme == "dark")
        butterfly(painter, self.width() - 29, self.height() - 140, 12, QColor("#9b86bc" if self.theme == "dark" else "#bda0e9"), 15)


class DecorativeCard(QFrame):
    def __init__(self, decoration: str = "flowers") -> None:
        super().__init__()
        self.theme = "light"
        self.decoration = decoration
        self.setObjectName("Card")

    def set_theme(self, theme: str) -> None:
        self.theme = theme
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setOpacity(.75)
        if self.decoration == "butterfly":
            butterfly(painter, self.width() - 24, 28, 10, QColor("#9b7ebd" if self.theme == "dark" else "#bba0e9"), 20)
        else:
            blossoms(painter, 10, self.height() - 13, .9, self.theme == "dark")


class IllustratedHero(QFrame):
    def __init__(self, artwork: Artwork) -> None:
        super().__init__()
        self.artwork = artwork
        self.theme = "light"
        self._scaled = QPixmap()
        self._scaled_size = QSize()
        self._scaled_dpr = 0.0
        self.setObjectName("IllustratedHero")
        self.setMinimumHeight(236)

    def set_theme(self, theme: str) -> None:
        self.theme = theme
        self.update()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "content_panel"):
            self.content_panel.setFixedWidth(max(265, int(self.width() * .53) - 25))

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)
        clip = QPainterPath()
        clip.addRoundedRect(rect, 17, 17)
        painter.setClipPath(clip)
        dark = self.theme == "dark"
        painter.fillRect(rect, QColor("#4b3449" if dark else "#fceaf1"))
        if not self.artwork.main.isNull():
            dpr = self.devicePixelRatioF()
            art_size = QSize(round(self.width() * .60), self.height())
            if self._scaled_size != art_size or self._scaled_dpr != dpr:
                physical_size = QSize(round(art_size.width() * dpr), round(art_size.height() * dpr))
                self._scaled = QPixmap(physical_size)
                self._scaled.fill(Qt.GlobalColor.transparent)
                source = self.artwork.main
                ratio = art_size.width() / max(1, art_size.height())
                source_height = min(float(source.height()), source.width() / max(.01, ratio))
                source_width = source_height * ratio
                source_rect = QRectF((source.width() - source_width) * .68, (source.height() - source_height) * .34, source_width, source_height)
                image_painter = QPainter(self._scaled)
                image_painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                image_painter.drawPixmap(QRectF(0, 0, physical_size.width(), physical_size.height()), source, source_rect)
                image_painter.end()
                self._scaled.setDevicePixelRatio(dpr)
                self._scaled_size = art_size
                self._scaled_dpr = dpr
            # 将抽象场景放在右侧，左侧保留文字空间。
            logical = self._scaled.deviceIndependentSize()
            painter.drawPixmap(round(self.width() * .40 + (art_size.width() - logical.width()) / 2), int((self.height() - logical.height()) * .34), self._scaled)
            if dark:
                painter.fillRect(rect, QColor(35, 23, 38, 110))
        veil = QLinearGradient(0, 0, self.width() * .80, 0)
        base = QColor("#302634" if dark else "#fff8fb")
        base.setAlpha(252)
        veil.setColorAt(0, base)
        base.setAlpha(240)
        veil.setColorAt(.50, base)
        base.setAlpha(120 if dark else 110)
        veil.setColorAt(.77, base)
        base.setAlpha(0)
        veil.setColorAt(1, base)
        painter.fillRect(rect, veil)
        butterfly(painter, self.width() * .47, 38, 10, QColor("#c88da8" if dark else "#efa5c1"))
        blossoms(painter, 7, self.height() - 12, 1.1, dark)
        painter.setClipping(False)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(colors(self.theme)["border"]), 1))
        painter.drawRoundedRect(rect, 17, 17)
