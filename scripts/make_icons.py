"""Build the app icons from clear/assets/icon.svg (developer tool; needs PyQt6 and Pillow).

    python3 scripts/make_icons.py

Writes, next to the SVG:
  icon.png       512 px, edge to edge   - window icon on Windows/Linux, sidebar
  icon-mac.png   1024 px, macOS layout  - Dock icon (body 824 px with margin and a soft shadow)
  icon.ico       16-256 px              - Windows shortcuts
  icon.icns      16-1024 px             - macOS app bundles
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image, ImageFilter  # noqa: E402
from PyQt6.QtCore import QBuffer, QIODevice, QRectF, Qt  # noqa: E402
from PyQt6.QtGui import QGuiApplication, QImage, QPainter  # noqa: E402
from PyQt6.QtSvg import QSvgRenderer  # noqa: E402

ASSETS = Path(__file__).resolve().parent.parent / "clear" / "assets"


def render(svg: QSvgRenderer, size: int) -> Image.Image:
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    svg.render(p, QRectF(0, 0, size, size))
    p.end()
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    from io import BytesIO

    return Image.open(BytesIO(bytes(buf.data()))).convert("RGBA")


def mac_layout(body: Image.Image, size: int = 1024) -> Image.Image:
    """Apple's grid: an 824/1024 body centred a little high, over a soft shadow."""
    scale = size / 1024
    inner = round(824 * scale)
    art = body.resize((inner, inner), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    alpha = art.split()[3].point(lambda a: int(a * 0.32))
    shadow.paste(Image.new("RGBA", art.size, (0, 0, 0, 255)), (round(100 * scale), round(112 * scale)), alpha)
    canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(radius=max(1, round(14 * scale)))))
    canvas.alpha_composite(art, (round(100 * scale), round(100 * scale)))
    return canvas


def main() -> int:
    app = QGuiApplication(sys.argv)  # QtSvg needs an application object
    svg = QSvgRenderer(str(ASSETS / "icon.svg"))
    big = render(svg, 1024)
    big.resize((512, 512), Image.LANCZOS).save(ASSETS / "icon.png", optimize=True)
    mac = mac_layout(big)
    mac.save(ASSETS / "icon-mac.png", optimize=True)
    sizes = [16, 24, 32, 48, 64, 128, 256]
    big.save(ASSETS / "icon.ico", sizes=[(s, s) for s in sizes])
    mac.save(ASSETS / "icon.icns")
    for name in ("icon.png", "icon-mac.png", "icon.ico", "icon.icns"):
        print(f"{name:14} {(ASSETS / name).stat().st_size / 1024:7.1f} KB")
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
