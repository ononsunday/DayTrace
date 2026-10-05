"""Generate original editable SVG scenery and a twelve-icon PNG atlas using Qt."""
from pathlib import Path
import sys

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "assets" / "art"

def render(svg, name, width, height):
    (ART / (name + ".svg")).write_text(svg, encoding="utf-8")
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    renderer = QSvgRenderer(svg.encode())
    if not renderer.isValid():
        raise ValueError("Invalid SVG: " + name)
    renderer.render(painter, QRectF(0, 0, width, height))
    painter.end()
    if not image.save(str(ART / (name + ".png"))):
        raise ValueError("Could not save " + name)

def generate():
    ART.mkdir(parents=True, exist_ok=True)
    petals = "".join(f'<ellipse cx="0" cy="-27" rx="13" ry="27" transform="rotate({angle})"/>' for angle in range(0, 360, 60))
    scene = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="1000" viewBox="0 0 1600 1000">
    <defs><linearGradient id="sky" x2="1" y2="1"><stop stop-color="#f8e4ed"/><stop offset="1" stop-color="#e7dcf3"/></linearGradient>
    <g id="flower" fill="#e9a4bf">{petals}<circle r="12" fill="#f6d497"/></g></defs>
    <rect width="1600" height="1000" fill="url(#sky)"/>
    <circle cx="1110" cy="250" r="130" fill="#fff1ce"/>
    <path d="M0 760 Q350 540 700 740 T1600 600 V1000 H0Z" fill="#d2c1df"/>
    <path d="M0 850 Q400 650 850 850 T1600 740 V1000 H0Z" fill="#efd2de"/>
    <path d="M970 650 Q1070 590 1145 615" fill="none" stroke="#a68aaf" stroke-width="12"/>
    <g transform="translate(1050 360)"><circle r="137" fill="#fff9f0" stroke="#b096bb" stroke-width="9"/>
    <path d="M0 -90 V0 L60 32" fill="none" stroke="#a482af" stroke-width="13" stroke-linecap="round"/>
    <circle r="10" fill="#c695ac"/></g>
    <use href="#flower" x="910" y="550"/><use href="#flower" x="1230" y="530" transform="rotate(12 1230 530)"/>
    <use href="#flower" x="1190" y="680"/>
    <g fill="#c3a3ce"><circle cx="860" cy="310" r="8"/><circle cx="1290" cy="350" r="9"/><circle cx="1170" cy="150" r="7"/></g>
    </svg>'''
    render(scene, "main-art", 1600, 1000)
    backdrop = '''<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="800" viewBox="0 0 1200 800">
    <rect width="1200" height="800" fill="#f7edf4"/><circle cx="1050" cy="110" r="160" fill="#ffedc9"/>
    <path d="M0 500 Q300 280 620 520 T1200 400 V800 H0Z" fill="#e0d0eb"/>
    <path d="M0 690 Q380 480 720 650 T1200 570 V800 H0Z" fill="#efd1df"/>
    </svg>'''
    render(backdrop, "backdrop", 1200, 800)
    icons = [
        '<path d="M28 58 L64 28 L100 58 V100 H75 V75 H53 V100 H28Z"/>',
        '<circle cx="64" cy="64" r="36"/><path d="M64 40 V64 L83 76"/>',
        '<path d="M30 97 V72 H43 V97 M57 97 V52 H70 V97 M84 97 V29 H97 V97"/>',
        '<path d="M28 31 H62 Q74 31 74 41 Q74 31 100 31 V95 H76 Q65 93 64 100 Q58 93 28 95Z M64 41 V94"/>',
        '<rect x="28" y="28" width="28" height="28" rx="5"/><rect x="72" y="28" width="28" height="28" rx="5"/><rect x="28" y="72" width="28" height="28" rx="5"/><rect x="72" y="72" width="28" height="28" rx="5"/>',
        '<path d="M28 42 H100 M28 64 H100 M28 86 H100"/><circle cx="48" cy="42" r="9"/><circle cx="80" cy="64" r="9"/><circle cx="57" cy="86" r="9"/>',
        '<path d="M79 30 L45 64 L79 98"/>',
        '<path d="M49 30 L83 64 L49 98"/>',
        '<rect x="27" y="35" width="74" height="66" rx="9"/><path d="M27 54 H101 M44 26 V43 M84 26 V43 M49 77 L59 87 L80 66"/>',
        '<path d="M48 35 V93 M80 35 V93"/>',
        '<path d="M32 87 L32 100 L45 100 L98 47 L81 30Z M72 39 L89 56"/>',
        '<path d="M38 31 H100 M38 64 H100 M38 97 H100"/><circle cx="24" cy="31" r="3"/><circle cx="24" cy="64" r="3"/><circle cx="24" cy="97" r="3"/>',
    ]
    cells = []
    for index, icon in enumerate(icons):
        x, y = index % 4 * 160, index // 4 * 160
        cells.append(f'<g transform="translate({x+16} {y+16})"><circle cx="64" cy="64" r="60" fill="#f8e6ef"/><g fill="none" stroke="#9273a4" stroke-width="6" stroke-linecap="round" stroke-linejoin="round">{icon}</g></g>')
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480" viewBox="0 0 640 480">' + ''.join(cells) + '</svg>'
    render(svg, "stickers", 640, 480)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    generate()
    print("Generated original SVG and PNG artwork.")
