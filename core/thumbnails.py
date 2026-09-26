"""
缩略图相关：缓存路径、生成、后台批量加载。

- library_cache_dir()          缩略图缓存目录（图库/cache/）
- cache_path_for(image_path)   某张图的缩略图缓存文件路径
- make_thumbnail(path, size)   用 Pillow 生成缩略图（QPixmap）
- load_or_make_thumbnail(path) 优先读缓存，未命中则生成并写回
- ThumbnailLoader              QThread，批量后台加载缩略图
"""

import hashlib
import io
import os

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QPixmap
from PIL import Image

import database


# 单文件超过 50MB 不生成缩略图（避免读超大图卡顿）
MAX_FILE_SIZE = 50 * 1024 * 1024


def library_cache_dir():
    """返回图库的 cache 目录（不存在则创建）。"""
    lib = database.get_library()
    p = os.path.join(lib, "cache")
    os.makedirs(p, exist_ok=True)
    return p


def cache_path_for(image_path):
    """
    缩略图缓存路径。
    按「路径 + 修改时间 + 大小」算 hash，文件被修改后缓存自动失效。
    """
    try:
        stat = os.stat(image_path)
        mtime = stat.st_mtime
        size = stat.st_size
    except OSError:
        mtime = 0
        size = 0

    key = f"{image_path}|{mtime}|{size}"
    h = hashlib.md5(key.encode("utf-8")).hexdigest()
    return os.path.join(library_cache_dir(), h + ".png")


def make_thumbnail(image_path, size=160):
    """用 PIL 生成缩略图，返回 QPixmap；失败返回 None。"""
    try:
        with Image.open(image_path) as img:
            img = img.convert("RGB")
            img.thumbnail((size, size), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            buf.seek(0)
            pixmap = QPixmap()
            pixmap.loadFromData(buf.getvalue(), "PNG")
            return pixmap
    except Exception:
        return None


def load_or_make_thumbnail(path):
    """
    优先读缩略图缓存；缓存缺失/损坏则现做并写回缓存。
    失败返回 None。
    """
    cf = cache_path_for(path)
    if os.path.exists(cf):
        pixmap = QPixmap(cf)
        if not pixmap.isNull():
            return pixmap
    pixmap = make_thumbnail(path)
    if pixmap is None:
        return None
    try:
        pixmap.save(cf, "PNG")
    except Exception:
        pass
    return pixmap


class ThumbnailLoader(QThread):
    """
    后台线程：批量生成/读取缩略图，分批发给主线程。

    信号：
      batch_ready(list)  一批 (path, pixmap)
      progress(done, total)
      finished_all()
    """

    batch_ready = Signal(list)
    progress = Signal(int, int)
    finished_all = Signal()

    BATCH_SIZE = 20

    def __init__(self, images):
        super().__init__()
        self.images = images
        self._stop = False

    def run(self):
        total = len(self.images)
        done = 0
        batch = []

        for path in self.images:
            if self._stop:
                break
            done += 1

            try:
                if os.path.getsize(path) > MAX_FILE_SIZE:
                    self.progress.emit(done, total)
                    continue
            except OSError:
                self.progress.emit(done, total)
                continue

            cache_file = cache_path_for(path)
            pixmap = None
            if os.path.exists(cache_file):
                pixmap = QPixmap(cache_file)
                if pixmap.isNull():
                    pixmap = None

            if pixmap is None:
                pixmap = make_thumbnail(path)
                if pixmap is None:
                    self.progress.emit(done, total)
                    continue
                pixmap.save(cache_file, "PNG")

            batch.append((path, pixmap))

            if len(batch) >= self.BATCH_SIZE:
                self.batch_ready.emit(batch)
                self.progress.emit(done, total)
                batch = []

        if batch:
            self.batch_ready.emit(batch)
        self.progress.emit(done, total)
        self.finished_all.emit()

    def stop(self):
        self._stop = True