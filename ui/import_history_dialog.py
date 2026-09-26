"""
导入历史对话框。

列出所有 sources（历史导入来源），支持"再次导入"和"移除来源"。
"""

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QPushButton,
    QMessageBox, QDialogButtonBox
)

import database


class ImportHistoryDialog(QDialog):
    """
    导入历史对话框。

    列出所有 sources。
      - 双击 / 回车 → 再次导入
      - 选中 + 点"移除来源" → 移除
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("导入历史")
        self.resize(700, 500)

        self._reimport_path = None
        self._need_refresh_main = False  # 如果移除了来源，通知主窗口刷新

        layout = QVBoxLayout(self)

        tip = QLabel(
            "以下是历史上执行过导入操作的来源文件夹。\n"
            "双击 / 回车：再次导入（创建新的导入批次）\n"
            "选中后点「移除来源」：删除该来源的未整理图片记录和导入历史（不动磁盘文件）"
        )
        tip.setStyleSheet("color: gray;")
        tip.setWordWrap(True)
        layout.addWidget(tip)

        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(self._on_double_clicked)
        layout.addWidget(self.list_widget)

        # 底部按钮
        btn_layout = QHBoxLayout()

        self.btn_reimport = QPushButton("再次导入")
        self.btn_reimport.clicked.connect(self._try_reimport)
        btn_layout.addWidget(self.btn_reimport)

        self.btn_remove = QPushButton("移除来源")
        self.btn_remove.clicked.connect(self._try_remove)
        btn_layout.addWidget(self.btn_remove)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        self.refresh()

    def refresh(self):
        self.list_widget.clear()

        sources = database.get_sources()
        if not sources:
            item = QListWidgetItem("（还没有导入历史）")
            item.setFlags(Qt.NoItemFlags)
            self.list_widget.addItem(item)
            return

        for src in sources:
            self._add_source_item(src)

    def _add_source_item(self, src):
        path = src.get("path", "")
        first_import = src.get("first_import")
        last_import = src.get("last_import")
        last_count = src.get("last_count")

        exists = os.path.isdir(path)

        lines = [path]
        if first_import:
            lines.append(f"  首次导入：{self._fmt_time(first_import)}")
        if last_import:
            lines.append(f"  最近导入：{self._fmt_time(last_import)}")
        if last_count is not None:
            lines.append(f"  最近新增：{last_count} 张")
        if not exists:
            lines.append("  ⚠ 来源文件夹不存在")

        text = "\n".join(lines)

        item = QListWidgetItem(text)
        item.setData(Qt.UserRole, src.get("id"))
        item.setData(Qt.UserRole + 1, path)
        self.list_widget.addItem(item)

    def _fmt_time(self, ts):
        if ts is None:
            return "—"
        import time
        try:
            return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))
        except Exception:
            return str(ts)

    # ---------- 交互 ----------

    def _on_double_clicked(self, item):
        self._try_reimport()

    def _try_reimport(self):
        item = self.list_widget.currentItem()
        if item is None:
            return

        path = item.data(Qt.UserRole + 1)
        if not path:
            return

        if not os.path.isdir(path):
            QMessageBox.warning(
                self, "来源不存在",
                f"来源文件夹不存在：\n{path}\n\n"
                "请确认磁盘或路径是否可用。"
            )
            return

        self._reimport_path = path
        self.accept()

    def _try_remove(self):
        item = self.list_widget.currentItem()
        if item is None:
            QMessageBox.information(self, "未选中", "请先选中一个来源。")
            return

        source_id = item.data(Qt.UserRole)
        path = item.data(Qt.UserRole + 1)
        if source_id is None or not path:
            return

        # 查询统计
        stats = database.get_source_stats(source_id)
        if stats is None:
            QMessageBox.warning(self, "错误", "该来源已不存在。")
            self.refresh()
            return

        external_count = stats["external_count"]
        batch_count = stats["batch_count"]

        reply = QMessageBox.question(
            self, "移除来源",
            f"确定要移除这个导入来源吗？\n\n"
            f"来源：{path}\n\n"
            f"将删除：\n"
            f"  - {external_count} 条未整理图片记录\n"
            f"  - {batch_count} 条导入批次\n\n"
            f"磁盘上的原文件不会被删除。\n"
            f"已整理进图库的图片不受影响。\n\n"
            f"确定继续吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        result = database.remove_source_completely(source_id)

        QMessageBox.information(
            self, "移除完成",
            f"已删除：\n"
            f"  {result['deleted_images']} 条图片记录\n"
            f"  {result['deleted_batches']} 条导入批次\n"
            f"  来源记录已移除"
        )

        self._need_refresh_main = True
        self.refresh()

    def get_reimport_path(self):
        return self._reimport_path

    def need_refresh_main(self):
        """调用方通过此方法判断是否需要刷新主窗口（未整理 Tab）。"""
        return self._need_refresh_main

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter:
            self._try_reimport()
            return
        if event.key() == Qt.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(event)