"""
后台导入线程。

用于把 scanner.import_folder 放到 QThread 里执行，
避免阻塞 UI。

信号：
  progress(done, total_or_None, found, new, skip)
  finished_import(result_dict)   # result_dict["status"] ∈ {"completed", "cancelled"}
  failed(error_message)          # 真正的异常
"""

from PySide6.QtCore import QThread, Signal

from core.scanner import import_folder


class ImportWorker(QThread):
    progress = Signal(int, object, int, int, int)
    finished_import = Signal(dict)
    failed = Signal(str)

    def __init__(self, folder_path, parent=None):
        super().__init__(parent)
        self.folder_path = folder_path
        self.cancel_requested = False

    def cancel(self):
        """请求取消。协作式：worker 会在安全检查点发现。"""
        self.cancel_requested = True

    def run(self):
        try:
            result = import_folder(
                self.folder_path,
                progress_callback=self._on_progress,
                cancel_check=lambda: self.cancel_requested,
            )
            self.finished_import.emit(result)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.failed.emit(str(e))

    def _on_progress(self, done, total, found, new, skip):
        self.progress.emit(done, total, found, new, skip)