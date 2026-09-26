"""
导入进度对话框。

模态对话框，显示导入进度，提供取消按钮。

线程安全原则：
  - 用户关闭窗口时，先请求取消，再等待 worker 结束
  - 绝不在 worker 还在运行时销毁 worker 对象
  - worker 结束后才能关闭对话框
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QProgressBar, QPushButton, QMessageBox
)


class ImportProgressDialog(QDialog):
    """
    导入进度对话框。

    用法：
        worker = ImportWorker(folder_path)
        dlg = ImportProgressDialog(folder_path, worker, parent)
        worker.start()
        dlg.exec()
        # dlg.exec() 返回时，worker 已结束
    """

    def __init__(self, folder_path, worker, parent=None):
        super().__init__(parent)
        self.folder_path = folder_path
        self.worker = worker

        self._closing = False  # 防止重入

        self.setWindowTitle("正在导入")
        self.setModal(True)
        self.resize(520, 240)

        # 禁止用户点 X 关闭（必须通过取消或等待完成）
        self.setWindowFlag(Qt.WindowCloseButtonHint, False)

        layout = QVBoxLayout(self)

        # 来源
        self.lbl_source = QLabel(f"来源：{folder_path}")
        self.lbl_source.setWordWrap(True)
        layout.addWidget(self.lbl_source)

        layout.addSpacing(10)

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # 初始为不确定模式
        layout.addWidget(self.progress_bar)

        # 状态文字
        self.lbl_status = QLabel("正在扫描……")
        layout.addWidget(self.lbl_status)

        layout.addSpacing(10)

        # 取消按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.clicked.connect(self.on_cancel_clicked)
        btn_layout.addWidget(self.btn_cancel)
        layout.addLayout(btn_layout)

        # 连接 worker 信号
        self.worker.progress.connect(self.on_progress)
        self.worker.finished_import.connect(self.on_finished)
        self.worker.failed.connect(self.on_failed)

    # ---------- 信号处理 ----------

    def on_progress(self, done, total, found, new, skip):
        """
        两阶段进度：
          - 扫描阶段：total is None
          - 登记阶段：total is int
        """
        if total is None:
            # 扫描阶段
            self.progress_bar.setRange(0, 0)  # 不确定
            self.lbl_status.setText(
                f"正在扫描……\n"
                f"已扫描 {done} 个文件\n"
                f"已发现 {found} 张图片"
            )
        else:
            # 登记阶段
            if total == 0:
                self.progress_bar.setRange(0, 1)
                self.progress_bar.setValue(1)
            else:
                self.progress_bar.setRange(0, total)
                self.progress_bar.setValue(done)
            self.lbl_status.setText(
                f"正在登记……\n"
                f"{done} / {total}\n"
                f"已新增 {new} 张，跳过 {skip} 张"
            )

    def on_finished(self, result):
        """worker 完成（completed 或 cancelled）。"""
        self._closing = True

        status = result.get("status", "completed")
        total_found = result.get("total_found", 0)
        new_count = result.get("new_count", 0)
        skip_count = result.get("skip_count", 0)

        # 确保 worker 线程已经结束
        self._wait_for_worker()

        if status == "cancelled":
            QMessageBox.information(
                self, "导入已取消",
                f"已取消导入。\n\n"
                f"已发现：{total_found} 张\n"
                f"已新增：{new_count} 张\n"
                f"已跳过：{skip_count} 张"
            )
        else:
            QMessageBox.information(
                self, "导入完成",
                f"发现：{total_found} 张\n"
                f"新增：{new_count} 张\n"
                f"跳过：{skip_count} 张"
            )

        self.accept()

    def on_failed(self, error_msg):
        """worker 失败。"""
        self._closing = True

        self._wait_for_worker()

        QMessageBox.warning(
            self, "导入失败",
            f"导入过程中发生错误：\n\n{error_msg}"
        )
        self.reject()

    def on_cancel_clicked(self):
        """用户点取消。"""
        if self._closing:
            return

        self.btn_cancel.setEnabled(False)
        self.btn_cancel.setText("取消中…")
        self.lbl_status.setText("正在取消，请稍候……")
        self.worker.cancel()

    # ---------- 关闭处理 ----------

    def _wait_for_worker(self):
        """
        等待 worker 线程真正结束。
        不主动 cancel——cancel 应该由 on_cancel_clicked / closeEvent 负责。
        """
        if self.worker is not None and self.worker.isRunning():
            self.worker.wait()

    def closeEvent(self, event):
        """
        用户尝试关闭窗口（虽然 X 按钮已禁用，但 Esc 等可能触发）。
        不直接关闭，改为请求取消。
        """
        if self._closing:
            event.accept()
            return

        # 请求取消，忽略关闭
        self.on_cancel_clicked()
        event.ignore()

    def keyPressEvent(self, event):
        """禁用 Esc 关闭。"""
        if event.key() == Qt.Key_Escape:
            event.ignore()
            return
        super().keyPressEvent(event)