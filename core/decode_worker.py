"""
DecodeWorker：后台解码线程。

职责：
  - 从队列里取出任务
  - 检查 generation
  - 读磁盘缓存或解码原图
  - 生成 QImage
  - emit 信号

线程边界：
  - Worker 线程：Pillow 解码、磁盘缓存读写、生成 QImage
  - GUI 线程：QImage → QPixmap

设计依据：
  《Phase 2A 设计：可见区域驱动的缩略图浏览架构》第六节
"""

import os
import queue

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage
from PIL import Image

from core.image_readers import init_image_readers


# 缩略图尺寸
THUMBNAIL_SIZE = 160

# 缓存版本
THUMBNAIL_CACHE_VERSION = 1


def _cache_dir():
    """返回缩略图缓存目录。"""
    import database
    lib = database.get_library()
    if lib:
        d = os.path.join(lib, "cache")
        os.makedirs(d, exist_ok=True)
        return d
    return None


def cache_path_for(image_path):
    """
    缩略图缓存路径。
    按「路径 + 修改时间 + 大小」算 hash，文件被修改后缓存自动失效。
    带 cache version。
    """
    import hashlib

    try:
        stat = os.stat(image_path)
        mtime = stat.st_mtime
        size = stat.st_size
    except OSError:
        mtime = 0
        size = 0

    key = f"{image_path}|{mtime}|{size}"
    h = hashlib.md5(key.encode("utf-8")).hexdigest()

    cache_dir = _cache_dir()
    if cache_dir is None:
        return None

    return os.path.join(
        cache_dir,
        f"v{THUMBNAIL_CACHE_VERSION}_{h}.png"
    )


def decode_image(file_path, max_side=THUMBNAIL_SIZE) -> QImage | None:
    """
    从原图解码并缩放到 max_side，返回 QImage。
    失败返回 None。

    对 JPEG 使用 draft() 加速（避免完整解码大图）。
    其他格式走完整解码 + 缩放。
    """
    try:
        init_image_readers()

        with Image.open(file_path) as img:
            # 对 JPEG 使用 draft()
            # draft 会在解码阶段就降采样，避免构造完整 RGB 图
            if img.format == "JPEG":
                try:
                    img.draft("RGB", (max_side * 2, max_side * 2))
                except Exception:
                    pass

            w, h = img.size
            if w > max_side or h > max_side:
                img.thumbnail((max_side, max_side), Image.LANCZOS)
            if img.mode != "RGB":
                img = img.convert("RGB")

            import io
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            data = buf.getvalue()

            qimage = QImage()
            qimage.loadFromData(data, "PNG")
            if qimage.isNull():
                return None
            return qimage

    except Exception:
        return None


class DecodeWorker(QThread):
    """
    后台解码线程。

    信号：
      thumbnail_generated(image_id, qimage, generation, token)
      decode_failed(image_id, error, generation, token)
    """

    thumbnail_generated = Signal(int, QImage, int, int)
    decode_failed = Signal(int, str, int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._queue = queue.PriorityQueue()
        self._stop = False
        self._current_generation = 0

    # ---------- 外部调用 ----------

    def enqueue(self, image_id, file_path, priority, generation, token):
        """
        把任务加入队列。

        priority: 数字越小越优先
        generation: 当前 generation
        token: 请求 token
        """
        self._queue.put((priority, image_id, file_path, generation, token))

    def reprioritize(self, image_id, new_priority, file_path, generation, token):
        """
        提升某 image_id 的优先级。
        直接再入队一条高优先级条目。旧条目也会被处理，但结果一致，无害。
        """
        self._queue.put(
            (new_priority, image_id, file_path, generation, token)
        )

    def set_generation(self, gen):
        self._current_generation = gen

    def stop(self):
        self._stop = True

    # ---------- 线程主体 ----------

    def run(self):
        while not self._stop:
            try:
                item = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue

            priority, image_id, file_path, gen, token = item

            # 检查 generation
            if gen != self._current_generation:
                continue

            try:
                qimage = self._decode_or_load_cache(file_path)

                # 解码后再检查一次 generation（因为解码可能耗时几秒）
                if gen != self._current_generation:
                    continue

                if qimage is None:
                    self.decode_failed.emit(
                        image_id, "decode returned None", gen, token
                    )
                else:
                    self.thumbnail_generated.emit(
                        image_id, qimage, gen, token
                    )
            except Exception as e:
                self.decode_failed.emit(image_id, str(e), gen, token)

    def _decode_or_load_cache(self, file_path) -> QImage | None:
        """先查磁盘缓存，未命中再解码。"""
        cache_file = cache_path_for(file_path)

        if cache_file and os.path.exists(cache_file):
            qimage = QImage(cache_file)
            if not qimage.isNull():
                return qimage
            # 缓存文件损坏，删掉
            try:
                os.remove(cache_file)
            except Exception:
                pass

        # 缓存未命中，从原图解码
        qimage = decode_image(file_path, THUMBNAIL_SIZE)
        if qimage is None:
            return None

        # 保存到缓存
        if cache_file:
            try:
                qimage.save(cache_file, "PNG")
            except Exception:
                pass

        return qimage