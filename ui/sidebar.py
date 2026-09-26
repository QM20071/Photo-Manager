"""
左侧栏：未整理 / 收藏 / 相册（可展开）。

支持拖拽放置：网格里拖过来的图片可以放到"未整理 / 收藏 / 相册子项"上。
"""

import os
import json

from PySide6.QtCore import Qt, Signal, QMimeData
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame
)
from PySide6.QtGui import QPainter, QColor

import database
from ui.theme import get_color_str


MIME_TYPE = "application/x-photo-image-ids"


class SidebarRow(QWidget):
    """左栏的一行：图标 + 文字 + 数字。可点击、可高亮、可作为拖放目标。"""

    clicked = Signal()
    arrow_clicked = Signal()

    def __init__(self, text, count=0, indent=0, arrow=None,
                 drop_target=None, parent=None):
        """
        drop_target: None / "未整理" / "收藏" / "album"
        """
        super().__init__(parent)
        self.setFixedHeight(32)
        self.setCursor(Qt.PointingHandCursor)
        self.setAcceptDrops(drop_target is not None)

        self._drop_target = drop_target
        self._drop_hover = False
        self._hovered = False
        self._selected = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8 + indent * 16, 0, 10, 0)
        layout.setSpacing(6)

        self.arrow_btn = None

        self.label = QLabel(text)
        layout.addWidget(self.label)
        layout.addStretch()

        self.count_label = QLabel(str(count) if count is not None else "")
        self.count_label.setStyleSheet("color: gray; font-size: 12px;")
        layout.addWidget(self.count_label)

        if arrow is not None:
            self.arrow_btn = QLabel("▸" if arrow == "right" else "▾")
            self.arrow_btn.setFixedSize(12, 16)
            self.arrow_btn.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.arrow_btn.setStyleSheet(
                "font-size: 11px; background: transparent;"
            )
            self.arrow_btn.setContentsMargins(0, 0, 3, 0)
            self.arrow_btn.setCursor(Qt.PointingHandCursor)
            layout.addWidget(self.arrow_btn)

    def set_selected(self, on):
        self._selected = on
        if on:
            self.label.setStyleSheet("color: #FFFFFF;")
            self.count_label.setStyleSheet(
                "color: #FFFFFF; font-size: 12px;"
            )
            if self.arrow_btn is not None:
                self.arrow_btn.setStyleSheet(
                    "font-size: 11px; background: transparent;"
                    "color: #FFFFFF;"
                )
        else:
            self.label.setStyleSheet("")
            self.count_label.setStyleSheet(
                "color: gray; font-size: 12px;"
            )
            if self.arrow_btn is not None:
                self.arrow_btn.setStyleSheet(
                    "font-size: 11px; background: transparent;"
                )
        self.update()

    def set_count(self, n):
        self.count_label.setText(str(n) if n is not None else "")

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)

        if self._drop_hover:
            painter.fillRect(self.rect(), QColor(76, 175, 80, 60))
            painter.setPen(QColor(76, 175, 80))
            painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
        elif self._selected:
            painter.fillRect(self.rect(), QColor(get_color_str("selected_bg")))
        elif self._hovered:
            painter.fillRect(self.rect(), QColor(0, 0, 0, 18))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            # 点三角区域 → 触发 arrow_clicked
            if self.arrow_btn is not None:
                rect = self.arrow_btn.geometry()
                if rect.contains(event.position().toPoint()):
                    self.arrow_clicked.emit()
                    return
            self.clicked.emit()
        super().mousePressEvent(event)

    # ----- 拖放 -----

    def dragEnterEvent(self, event):
        if self._drop_target is None:
            return
        if event.mimeData().hasFormat(MIME_TYPE):
            self._drop_hover = True
            self.update()
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self._drop_hover = False
        self.update()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self._drop_hover = False
        self.update()
        if self._drop_target is None:
            return
        if not event.mimeData().hasFormat(MIME_TYPE):
            return

        raw = bytes(event.mimeData().data(MIME_TYPE)).decode("utf-8")
        try:
            image_ids = json.loads(raw)
        except Exception:
            return

        if not image_ids:
            return

        win = self.window()
        if not hasattr(win, "handle_drop_on_sidebar"):
            return

        if self._drop_target == "album":
            win.handle_drop_on_sidebar("album", image_ids, self.label.text())
        else:
            win.handle_drop_on_sidebar(self._drop_target, image_ids, None)

        event.acceptProposedAction()


class SidebarLeft(QWidget):
    """左侧栏主控件。"""

    nav_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SidebarLeft")
        self._current_nav = "未整理"
        self._albums_expanded = False
        self._album_rows = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setObjectName("sidebar_left_scroll")
        self._apply_scroll_style()

        scroll = self.scroll
        container = QWidget()
        self.layout_main = QVBoxLayout(container)
        self.layout_main.setContentsMargins(4, 6, 4, 6)
        self.layout_main.setSpacing(2)

        self.row_unsorted = SidebarRow(
            "未整理", 0, drop_target="未整理"
        )
        self.row_unsorted.clicked.connect(
            lambda: self._on_nav_clicked("未整理")
        )
        self.layout_main.addWidget(self.row_unsorted)

        self.row_fav = SidebarRow(
            "收藏", 0, drop_target="收藏"
        )
        self.row_fav.clicked.connect(
            lambda: self._on_nav_clicked("收藏")
        )
        self.layout_main.addWidget(self.row_fav)

        self.row_albums = SidebarRow(
            "相册", "", arrow="right"
        )
        self.row_albums.clicked.connect(
            lambda: self._on_nav_clicked("相册")
        )
        if self.row_albums.arrow_btn is not None:
            self.row_albums.arrow_clicked.connect(self.toggle_albums)
        self.layout_main.addWidget(self.row_albums)

        self.albums_container = QWidget()
        self.albums_layout = QVBoxLayout(self.albums_container)
        self.albums_layout.setContentsMargins(0, 0, 0, 0)
        self.albums_layout.setSpacing(2)
        self.albums_container.setVisible(False)
        self.layout_main.addWidget(self.albums_container)

        self.layout_main.addStretch()

        scroll.setWidget(container)
        outer.addWidget(scroll)

        self._update_selected_style()

    # ---------- 交互 ----------

    def _on_nav_clicked(self, nav):
        self._current_nav = nav
        self._update_selected_style()
        self.nav_changed.emit(nav)

    def toggle_albums(self):
        self._albums_expanded = not self._albums_expanded
        self.albums_container.setVisible(self._albums_expanded)

        if self.row_albums.arrow_btn is not None:
            self.row_albums.arrow_btn.setText(
                "▾" if self._albums_expanded else "▸"
            )

        if self._albums_expanded:
            self.reload_albums()

    def _update_selected_style(self):
        self.row_unsorted.set_selected(self._current_nav == "未整理")
        self.row_fav.set_selected(self._current_nav == "收藏")
        self.row_albums.set_selected(self._current_nav == "相册")

    # ---------- 数据 ----------

    def set_counts(self, unsorted_count, fav_count):
        self.row_unsorted.set_count(unsorted_count)
        self.row_fav.set_count(fav_count)

    def reload_albums(self):
        for row in self._album_rows:
            row.setParent(None)
            row.deleteLater()
        self._album_rows.clear()

        for name in sorted(self._list_albums_safe()):
            count = self._count_album_files(name)
            row = SidebarRow(
                name, count, indent=2,
                drop_target="album"
            )
            row.clicked.connect(
                lambda n=name: self.album_selected_signal(n)
            )
            self.albums_layout.addWidget(row)
            self._album_rows.append(row)

    def album_selected_signal(self, name):
        win = self.window()
        if hasattr(win, "enter_album"):
            win.enter_album(name)

    def _list_albums_safe(self):
        try:
            from core.scanner import list_albums
            return list_albums()
        except Exception:
            return []

    def _count_album_files(self, album_name):
        lib = database.get_library()
        if not lib:
            return 0
        folder = os.path.join(lib, album_name)
        if not os.path.isdir(folder):
            return 0
        from core.scanner import IMAGE_EXTS
        count = 0
        for root, _, files in os.walk(folder):
            for f in files:
                if os.path.splitext(f)[1].lower() in IMAGE_EXTS:
                    count += 1
        return count

    def refresh_theme(self):
        self._apply_scroll_style()

    def _apply_scroll_style(self):
        bg = get_color_str("sidebar_bg")
        self.scroll.setStyleSheet(
            f"QScrollArea {{"
            f"  background-color: {bg};"
            f"  border: none;"
            f"}}"
            f"QScrollArea > QWidget > QWidget {{"
            f"  background-color: {bg};"
            f"}}"
        )

    def current_nav(self):
        return self._current_nav