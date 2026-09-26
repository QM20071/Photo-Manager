"""
各种对话框（Phase C：新模型）。

- DeleteWarningDialog   首次删除图片时的 3 秒倒计时提示
- ImportFolderDialog    （预留，Phase 2 使用）
- BlacklistDialog       管理黑名单
"""

import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QFileDialog, QMessageBox,
    QInputDialog, QDialogButtonBox
)

import config
import database


ALBUM_NAME_MAX_CHARS = 8


class DeleteWarningDialog(QDialog):
    """首次删除图片时的 3 秒倒计时提示。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("注意")
        self.resize(420, 180)
        self.setWindowFlag(Qt.WindowCloseButtonHint, False)

        layout = QVBoxLayout(self)

        msg = QLabel(
            "删除会把图片直接移到 Windows 回收站。\n\n"
            "你可以在系统回收站里还原它们。\n\n"
            "此提示只显示一次。"
        )
        msg.setWordWrap(True)
        msg.setStyleSheet("font-size: 14px; padding: 10px;")
        layout.addWidget(msg)

        layout.addStretch()

        self.btn_ok = QPushButton("确认（3）")
        self.btn_ok.setEnabled(False)
        self.btn_ok.clicked.connect(self.accept)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_ok)
        layout.addLayout(btn_layout)

        self._count = 3
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)

    def _tick(self):
        self._count -= 1
        if self._count <= 0:
            self._timer.stop()
            self.btn_ok.setText("确认")
            self.btn_ok.setEnabled(True)
        else:
            self.btn_ok.setText(f"确认（{self._count}）")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            event.ignore()
        else:
            super().keyPressEvent(event)


class ImportFolderDialog(QDialog):
    """
    导入文件夹对话框（Phase 2 详细实现）。

    Phase C 版本：仅作为占位，实际导入在 main.py 里调用 scanner.import_folder。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("导入文件夹")
        self.resize(560, 400)

        layout = QVBoxLayout(self)

        tip = QLabel(
            "导入会把外部文件夹里的图片登记到数据库，但不会移动原文件。\n"
            "如果你要真正整理图片进图库，请在导入后使用「整理」操作。"
        )
        tip.setStyleSheet("color: gray;")
        tip.setWordWrap(True)
        layout.addWidget(tip)

        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget)

        btn_layout = QHBoxLayout()
        btn_add = QPushButton("+ 添加文件夹")
        btn_add.clicked.connect(self.add_path)
        btn_layout.addWidget(btn_add)

        btn_remove = QPushButton("- 移除选中")
        btn_remove.clicked.connect(self.remove_selected)
        btn_layout.addWidget(btn_remove)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        self.refresh()

    def refresh(self):
        self.list_widget.clear()
        for src in database.get_sources():
            self.list_widget.addItem(QListWidgetItem(src["path"]))

    def add_path(self):
        folder = QFileDialog.getExistingDirectory(
            self, "选择要导入的文件夹（图库外部）"
        )
        if not folder:
            return
        folder = os.path.normpath(folder)

        # 安全检查
        lib = database.get_library()
        if lib:
            lib_norm = os.path.normcase(os.path.normpath(lib))
            folder_norm = os.path.normcase(folder)
            if folder_norm == lib_norm:
                QMessageBox.warning(self, "不允许", "不能导入图库本身")
                return
            if folder_norm.startswith(lib_norm + os.sep):
                QMessageBox.warning(self, "不允许", "不能导入图库内部的文件夹")
                return

        self.list_widget.addItem(QListWidgetItem(folder))

    def remove_selected(self):
        item = self.list_widget.currentItem()
        if item is None:
            return
        self.list_widget.takeItem(self.list_widget.row(item))


class BlacklistDialog(QDialog):
    """管理黑名单。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("管理黑名单")
        self.resize(600, 420)

        layout = QVBoxLayout(self)

        tip = QLabel("黑名单中的图库子文件夹不会被当作相册；其内容会进入「未整理」")
        tip.setStyleSheet("color: gray;")
        tip.setWordWrap(True)
        layout.addWidget(tip)

        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget)

        btn_layout = QHBoxLayout()

        btn_add = QPushButton("+ 从图库添加文件夹")
        btn_add.clicked.connect(self.add_from_library)
        btn_layout.addWidget(btn_add)

        btn_remove = QPushButton("- 移除选中")
        btn_remove.clicked.connect(self.remove_selected)
        btn_layout.addWidget(btn_remove)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        btns = QDialogButtonBox(QDialogButtonBox.Ok)
        btns.accepted.connect(self.accept)
        layout.addWidget(btns)

        self.refresh()

    def refresh(self):
        self.list_widget.clear()

        lib = database.get_library()
        all_names = database.get_blacklist_names()

        for name in all_names:
            if name in ("data", "cache"):
                self.list_widget.addItem(QListWidgetItem(name))
                continue

            full = os.path.join(lib, name) if lib else None
            if full and os.path.isdir(full):
                self.list_widget.addItem(QListWidgetItem(name))
            else:
                database.remove_from_blacklist(name)

    def add_from_library(self):
        lib = database.get_library()
        if not lib or not os.path.isdir(lib):
            QMessageBox.warning(self, "错误", "图库路径无效")
            return

        blacklist = set(database.get_blacklist_names())

        candidates = []
        for name in os.listdir(lib):
            full = os.path.join(lib, name)
            if not os.path.isdir(full):
                continue
            if name in ("data", "cache"):
                continue
            if name in blacklist:
                continue
            candidates.append(name)

        if not candidates:
            QMessageBox.information(
                self, "没有可选文件夹",
                "图库根目录下没有可加入黑名单的子文件夹。"
            )
            return

        name, ok = QInputDialog.getItem(
            self, "选择文件夹",
            "选择要加入黑名单的图库子文件夹：",
            sorted(candidates), 0, False
        )
        if not ok or not name:
            return

        database.add_to_blacklist(name)
        self.refresh()

    def remove_selected(self):
        item = self.list_widget.currentItem()
        if item is None:
            return
        name = item.text()
        if name in ("data", "cache"):
            QMessageBox.information(
                self, "不可移除",
                f"「{name}」是软件必需目录，不能移除"
            )
            return

        database.remove_from_blacklist(name)
        self.refresh()