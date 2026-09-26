"""
ThumbnailManager：缩略图管理器。

职责：
  - 接收 View 的请求（image_id + priority）
  - 检查 Memory LRU
  - 未命中则从 Model 取 file_path，派发给 DecodeWorker
  - 接收 Worker 结果，三重检查（generation + token + state）
  - 有效则 QImage → QPixmap，存入 LRU，emit thumbnail_ready
  - 处理 invalidate / bump_generation

设计依据：
  《Phase 2A 设计：可见区域驱动的缩略图浏览架构》第五、十、十一、十二节
"""

from collections import OrderedDict

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QPixmap

from core.decode_worker import DecodeWorker


# 优先级
PRIORITY_VISIBLE = 0
PRIORITY_PREFETCH = 1
PRIORITY_BACKGROUND = 2


# 状态
class ThumbState:
    UNKNOWN = 0
    QUEUED = 1
    LOADING = 2
    LOADED = 3
    FAILED = 4


class RequestState:
    def __init__(self, state, generation, priority=None, token=None):
        self.state = state
        self.generation = generation
        self.priority = priority
        self.token = token


class MemoryThumbnailCache:
    """有限容量的内存 LRU。"""

    def __init__(self, max_bytes):
        self.max_bytes = max_bytes
        self._cache = OrderedDict()
        self._current_bytes = 0

    def get(self, image_id):
        if image_id in self._cache:
            self._cache.move_to_end(image_id)
            return self._cache[image_id]
        return None

    def put(self, image_id, pixmap):
        if image_id in self._cache:
            self._cache.move_to_end(image_id)
            return
        self._cache[image_id] = pixmap
        self._current_bytes += self._estimate_size(pixmap)
        self._evict_if_needed()

    def pop(self, image_id):
        if image_id in self._cache:
            pixmap = self._cache.pop(image_id)
            self._current_bytes -= self._estimate_size(pixmap)

    def _estimate_size(self, pixmap):
        return pixmap.width() * pixmap.height() * 4

    def _evict_if_needed(self):
        while self._current_bytes > self.max_bytes and self._cache:
            _, evicted = self._cache.popitem(last=False)
            self._current_bytes -= self._estimate_size(evicted)


class ThumbnailManager(QObject):
    """
    缩略图管理器。

    信号：
      thumbnail_ready(image_id, pixmap)
    """

    thumbnail_ready = Signal(int, QPixmap)

    def __init__(self, model, worker, max_bytes=100 * 1024 * 1024, parent=None):
        """
        model: ImageListModel
        worker: DecodeWorker
        max_bytes: Memory LRU 容量（默认 100MB，待测）
        """
        super().__init__(parent)
        self._model = model
        self._worker = worker
        self._states = {}
        self._memory_cache = MemoryThumbnailCache(max_bytes)
        self._generation = 0
        self._request_tokens = {}

        self._worker.thumbnail_generated.connect(self._on_thumbnail_generated)
        self._worker.decode_failed.connect(self._on_decode_failed)

    # ---------- 请求 ----------

    def request(self, image_id, priority):
        file_path = self._model.get_file_path(image_id)
        file_path = self._model.get_file_path(image_id)
        if file_path is None:
            return

        state_info = self._states.get(image_id)

        # 情况 1：没有状态，或状态来自旧 generation
        if state_info is None or state_info.generation != self._generation:
            token = self._current_token(image_id)
            self._states[image_id] = RequestState(
                state=ThumbState.QUEUED,
                generation=self._generation,
                priority=priority,
                token=token,
            )
            self._worker.enqueue(
                image_id, file_path, priority,
                self._generation, token
            )
            return

        # 情况 2：已 LOADED
        if state_info.state == ThumbState.LOADED:
            pixmap = self._memory_cache.get(image_id)
            if pixmap is not None:
                self.thumbnail_ready.emit(image_id, pixmap)
            else:
                token = self._current_token(image_id)
                state_info.state = ThumbState.QUEUED
                state_info.priority = priority
                self._worker.enqueue(
                    image_id, file_path, priority,
                    self._generation, token
                )
            return

        # 情况 3：QUEUED / LOADING
        if state_info.state in (ThumbState.QUEUED, ThumbState.LOADING):
            if priority < (state_info.priority or 999):
                state_info.priority = priority
                self._worker.reprioritize(
                    image_id, priority, file_path,
                    self._generation, state_info.token
                )
            return

        # 情况 4：FAILED
        if state_info.state == ThumbState.FAILED:
            old_token = self._request_tokens.get(image_id, 0)
            new_token = old_token + 1
            self._request_tokens[image_id] = new_token

            self._states[image_id] = RequestState(
                state=ThumbState.QUEUED,
                generation=self._generation,
                priority=priority,
                token=new_token,
            )
            self._worker.enqueue(
                image_id, file_path, priority,
                self._generation, new_token
            )
            return

    def request_many(self, image_ids, priority):
        for image_id in image_ids:
            self.request(image_id, priority)

    def get_cached(self, image_id):
        return self._memory_cache.get(image_id)

    # ---------- 失效 ----------

    def invalidate(self, image_id):
        old_token = self._request_tokens.get(image_id, 0)
        self._request_tokens[image_id] = old_token + 1
        self._states.pop(image_id, None)
        self._memory_cache.pop(image_id, None)

    def bump_generation(self):
        self._generation += 1
        self._worker.set_generation(self._generation)
        self._states = {
            k: v for k, v in self._states.items()
            if v.generation == self._generation
        }
        return self._generation

    def current_generation(self):
        return self._generation

    # ---------- 内部 ----------

    def _current_token(self, image_id):
        token = self._request_tokens.get(image_id, 0)
        if token == 0:
            token = 1
            self._request_tokens[image_id] = token
        return token

    def _on_thumbnail_generated(self, image_id, qimage, gen, token):
        # 检查 1：generation
        if gen != self._generation:
            return

        # 检查 2：request_token
        current_token = self._request_tokens.get(image_id, 0)
        if token != current_token:
            return

        # 检查 3：当前状态
        state_info = self._states.get(image_id)
        if state_info is None:
            return
        if state_info.generation != self._generation:
            return
        if state_info.state not in (ThumbState.QUEUED, ThumbState.LOADING):
            return

        # 接受
        pixmap = QPixmap.fromImage(qimage)
        self._memory_cache.put(image_id, pixmap)
        self._states[image_id] = RequestState(
            state=ThumbState.LOADED,
            generation=self._generation,
            token=token,
        )
        self.thumbnail_ready.emit(image_id, pixmap)

    def _on_decode_failed(self, image_id, error, gen, token):
        print(f"[failed] id={image_id} err={error} gen={gen} cur={self._generation}")
        if gen != self._generation:
            return
        current_token = self._request_tokens.get(image_id, 0)
        if token != current_token:
            return
        state_info = self._states.get(image_id)
        if state_info is None:
            return
        if state_info.generation != self._generation:
            return
        if state_info.state not in (ThumbState.QUEUED, ThumbState.LOADING):
            return

        self._states[image_id] = RequestState(
            state=ThumbState.FAILED,
            generation=self._generation,
            token=token,
        )