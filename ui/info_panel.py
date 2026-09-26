"""
右侧信息栏：显示选中图片 / 相册 / 当前区域的信息。
"""

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QFrame, QScrollArea
)

from core.metadata import format_size, format_time
from ui.theme import get_color_str

class InfoPanel(QWidget):
    """右栏信息面板。"""

    def __init__(self, parent=None):
        super().__init__(parent)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setObjectName("info_panel_scroll")
        self._apply_scroll_style()

        scroll = self.scroll
        scroll.setStyleSheet(
            f"QScrollArea {{"
            f"  background-color: {get_color_str('sidebar_bg')};"
            f"  border: none;"
            f"}}"
            f"QScrollArea > QWidget > QWidget {{"
            f"  background-color: {get_color_str('sidebar_bg')};"
            f"}}"
        )
        
        container = QWidget()
        self.layout_main = QVBoxLayout(container)
        self.layout_main.setContentsMargins(10, 10, 10, 10)
        self.layout_main.setSpacing(8)

        # 内容区（动态填充）
        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(6)
        self.layout_main.addWidget(self.content)

        self.layout_main.addStretch()

        scroll.setWidget(container)
        outer.addWidget(scroll, 1)

        # 底部状态文字
        self.status_label = QLabel("")
        self.status_label.setStyleSheet(
            "color: gray; font-size: 12px; padding: 6px;"
        )
        self.status_label.setWordWrap(True)
        outer.addWidget(self.status_label)
        
        self.setObjectName("InfoPanel")

        self.clear()

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

    # ---------- 对外接口 ----------

    def clear(self):
        """无内容。"""
        self._set_content("信息", [])

    def show_message(self, title, lines):
        """显示标题 + 多行文字。lines: [(label, value), ...]"""
        self._set_content(title, lines)

    # ---------- 内部 ----------

    def _set_content(self, title, lines):
        # 清空
        while self.content_layout.count():
            child = self.content_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        # 第一行：名字（灰）+ 值
        first = self._make_row("名字", title)
        self.content_layout.addWidget(first)

        for label, value in lines:
            row = self._make_row(label, value)
            self.content_layout.addWidget(row)

    def _make_row(self, label, value):
        w = QWidget()
        w_layout = QVBoxLayout(w)
        w_layout.setContentsMargins(0, 0, 0, 0)
        w_layout.setSpacing(2)

        lbl = QLabel(label)
        lbl.setStyleSheet("color: gray; font-size: 12px;")
        w_layout.addWidget(lbl)

        val = QLabel(str(value) if value else "")
        val.setWordWrap(True)
        val.setStyleSheet("font-size: 13px;")
        val.setTextInteractionFlags(Qt.TextSelectableByMouse)
        w_layout.addWidget(val)

        return w