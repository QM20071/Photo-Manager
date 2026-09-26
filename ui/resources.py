"""
资源路径统一管理 + SVG 动态染色。

- icon_path(name)  返回图标文件路径（不染色，兼容旧调用）
- icon(name)       返回染色后的 QIcon（按当前主题）
- icon_pixmap(name, size)  返回染色后的 QPixmap
"""

import sys
from pathlib import Path

from PySide6.QtCore import Qt, QByteArray
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor
from PySide6.QtSvg import QSvgRenderer


def _app_dir() -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


APP_DIR = _app_dir()
RESOURCES_DIR = APP_DIR / "resources"
ICONS_DIR = RESOURCES_DIR / "icons"


def icon_path(name: str) -> str:
    """返回原始 SVG 路径（未染色）。"""
    return str(ICONS_DIR / f"{name}.svg")


def _load_svg_text(name: str) -> str | None:
    """读取 SVG 文本。失败返回 None。"""
    path = ICONS_DIR / f"{name}.svg"
    if not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _colored_svg_bytes(name: str) -> QByteArray | None:
    """
    读 SVG，把 #000000 替换成当前主题文字色，返回字节。
    """
    text = _load_svg_text(name)
    if text is None:
        return None

    # 延迟 import，避免循环依赖
    from ui.theme import get_color_str
    color = get_color_str("text")

    text = text.replace("#000000", color)
    text = text.replace("#000", color)
    text = text.replace('"black"', f'"{color}"')

    return QByteArray(text.encode("utf-8"))


def icon(name: str, size: int = 24) -> QIcon:
    data = _colored_svg_bytes(name)
    if data is None:
        return QIcon()

    renderer = QSvgRenderer(data)
    if not renderer.isValid():
        return QIcon()

    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()

    return QIcon(pixmap)