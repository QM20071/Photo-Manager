import hashlib
import io
import os

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QPushButton, QVBoxLayout,
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap, QImage, QMovie, QTransform
from PIL import Image

from core.image_readers import init_image_readers

import database


PREVIEW_MAX_SIDE = 1024


# ---------- 预览缓存 ----------

def _safe_cache_dir():
    """返回查看器预览缓存目录：图库/cache/preview/；失败则退回用户目录。"""
    try:
        lib = database.get_library()
        if lib and os.path.isdir(lib):
            d = os.path.join(lib, "cache", "preview")
            os.makedirs(d, exist_ok=True)
            return d
    except Exception:
        pass

    d = os.path.join(os.path.expanduser("~"), ".photo_manager_preview_cache")
    os.makedirs(d, exist_ok=True)
    return d


def _safe_cache_path_for(image_path):
    """
    预览缓存路径。
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
    return os.path.join(_safe_cache_dir(), h + ".png")


def load_pixmap_safe(path):
    """
    安全加载图片为 QPixmap：
      - 先用缓存（1024px 上限的 PNG），命中直接返回
      - 未命中则用 PIL 缩放、转 RGB、写缓存
      - 任何失败返回空 QPixmap
    """
    cache_file = _safe_cache_path_for(path)
    if os.path.exists(cache_file):
        pixmap = QPixmap(cache_file)
        if not pixmap.isNull():
            return pixmap

    try:
        with Image.open(path) as img:
            img = img.convert("RGB")
            w, h = img.size
            if w > PREVIEW_MAX_SIDE or h > PREVIEW_MAX_SIDE:
                img.thumbnail((PREVIEW_MAX_SIDE, PREVIEW_MAX_SIDE),
                              Image.LANCZOS)

            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            data = buf.getvalue()

            qimg = QImage()
            qimg.loadFromData(data, "JPEG")
            if qimg.isNull():
                return QPixmap()

            pixmap = QPixmap.fromImage(qimg)

            try:
                with open(cache_file, "wb") as f:
                    f.write(data)
            except Exception:
                pass

            return pixmap
    except Exception:
        return QPixmap()


def is_gif(path):
    return os.path.splitext(path)[1].lower() == ".gif"


# ---------- 静态图视图 ----------

class ImageView(QGraphicsView):
    """支持滚轮缩放、拖动平移的图片显示控件。"""

    ZOOM_STEP = 1.15
    MAX_SCALE = 4.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRenderHints(
            self.renderHints() | self.renderHints().SmoothPixmapTransform
        )
        self.setDragMode(QGraphicsView.NoDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("background-color: #222; border: none;")
        self.setFocusPolicy(Qt.NoFocus)

        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)

        self._item = QGraphicsPixmapItem()
        self._scene.addItem(self._item)

        self._pixmap = None
        self._dragging = False
        self._drag_start = None

    # ----- 内容设置 -----

    def set_pixmap(self, pixmap):
        """设置新图并重置视图（适应窗口）。"""
        self._pixmap = pixmap
        self._item.setPixmap(pixmap)
        if pixmap.isNull():
            self._scene.setSceneRect(0, 0, 0, 0)
        else:
            self._scene.setSceneRect(0, 0, pixmap.width(), pixmap.height())
        self.fit_to_window()

    def update_pixmap(self, pixmap):
        """更新当前图内容（GIF 换帧），不重置视图。"""
        if pixmap.isNull():
            return
        self._pixmap = pixmap
        self._item.setPixmap(pixmap)
        self._scene.setSceneRect(0, 0, pixmap.width(), pixmap.height())

    def clear(self):
        self._pixmap = None
        self._item.setPixmap(QPixmap())
        self._scene.setSceneRect(0, 0, 0, 0)

    # ----- 缩放 / 适应 -----

    def fit_to_window(self):
        if self._pixmap is None or self._pixmap.isNull():
            return
        self.resetTransform()
        self.fitInView(self._item, Qt.KeepAspectRatio)

    def zoom_in(self):
        self._zoom(self.ZOOM_STEP, center=True)

    def zoom_out(self):
        self._zoom(1 / self.ZOOM_STEP, center=True)

    def _zoom(self, factor, center=False):
        if self._pixmap is None or self._pixmap.isNull():
            return

        current = self.transform().m11()
        new_scale = current * factor

        if new_scale > self.MAX_SCALE:
            if current >= self.MAX_SCALE:
                return
            factor = self.MAX_SCALE / current

        anchor = (QGraphicsView.AnchorViewCenter if center
                  else QGraphicsView.AnchorUnderMouse)
        self.setTransformationAnchor(anchor)
        self.scale(factor, factor)

    # ----- 事件 -----

    def wheelEvent(self, event):
        if self._pixmap is None or self._pixmap.isNull():
            return
        if event.angleDelta().y() > 0:
            self._zoom(self.ZOOM_STEP)
        else:
            self._zoom(1 / self.ZOOM_STEP)
        event.accept()

    def mousePressEvent(self, event):
        if (event.button() == Qt.LeftButton
                and self._pixmap is not None
                and not self._pixmap.isNull()):
            self._dragging = True
            self._drag_start = event.position().toPoint()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging and self._drag_start is not None:
            delta = event.position().toPoint() - self._drag_start
            self._drag_start = event.position().toPoint()
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - delta.x()
            )
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - delta.y()
            )
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = False
            self.setCursor(Qt.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)


# ---------- 查看器窗口 ----------

class ImageViewer(QMainWindow):
    favorite_changed = Signal(int, bool)
    closed = Signal()

    def __init__(self, images, index):
        super().__init__()

        self.images = images          # 显示用的真实路径列表
        self.index = index
        self.rotation = 0
        self.movie = None
        self._is_gif = False

        self.setWindowTitle("查看图片")
        self.resize(1000, 750)

        # ----- 顶部工具栏 -----
        self.toolbar = QWidget()
        tb_layout = QHBoxLayout(self.toolbar)
        tb_layout.setContentsMargins(6, 4, 6, 4)
        tb_layout.setSpacing(6)

        self.btn_ccw = QPushButton("↺ 逆时针 (Q)")
        self.btn_ccw.clicked.connect(self.rotate_ccw)
        tb_layout.addWidget(self.btn_ccw)

        self.btn_cw = QPushButton("↻ 顺时针 (E)")
        self.btn_cw.clicked.connect(self.rotate_cw)
        tb_layout.addWidget(self.btn_cw)

        tb_layout.addStretch()

        btn_sys = QPushButton("用系统看图打开 (空格)")
        btn_sys.clicked.connect(self.open_in_system)
        tb_layout.addWidget(btn_sys)

        # ----- 视图 -----
        self.image_view = ImageView()

        container = QWidget()
        v = QVBoxLayout(container)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addWidget(self.toolbar)
        v.addWidget(self.image_view, stretch=1)
        self.setCentralWidget(container)

        self.setFocusPolicy(Qt.StrongFocus)
        self.setFocus()

        self.show_current()

    # ----- 当前 image_id -----

    def _current_image_id(self):
        """
        根据当前真实路径反查 image_id。
        查不到返回 None。
        """
        path = self.images[self.index]
        try:
            row = database.get_image_by_path(
                self._db_path_of(path), self._storage_type_of(path)
            )
        except Exception:
            return None
        return row["id"] if row else None

    def _db_path_of(self, real_path):
        lib = database.get_library()
        if lib:
            lib_norm = os.path.normcase(os.path.normpath(lib))
            path_norm = os.path.normcase(os.path.normpath(real_path))
            if path_norm.startswith(lib_norm + os.sep):
                return os.path.relpath(real_path, lib)
        return os.path.normpath(real_path)

    def _storage_type_of(self, real_path):
        lib = database.get_library()
        if lib:
            lib_norm = os.path.normcase(os.path.normpath(lib))
            path_norm = os.path.normcase(os.path.normpath(real_path))
            if path_norm.startswith(lib_norm + os.sep):
                return "managed"
        return "external"

    # ----- 显示当前图片 -----

    def show_current(self):
        path = self.images[self.index]

        self._stop_movie()
        self._is_gif = is_gif(path)

        self.btn_ccw.setVisible(not self._is_gif)
        self.btn_cw.setVisible(not self._is_gif)

        if self._is_gif and self._show_gif(path):
            return

        pixmap = load_pixmap_safe(path)
        if pixmap.isNull():
            self.image_view.clear()
            self.update_title()
            return

        if self.rotation != 0:
            pixmap = pixmap.transformed(
                QTransform().rotate(self.rotation),
                Qt.SmoothTransformation
            )

        self.image_view.set_pixmap(pixmap)
        self.update_title()

    def _show_gif(self, path):
        """尝试以 GIF 显示；成功返回 True。"""
        self.movie = QMovie(path)
        if not self.movie.isValid():
            self.movie = None
            self._is_gif = False
            return False

        self.movie.setCacheMode(QMovie.CacheAll)
        self.movie.frameChanged.connect(self._on_gif_frame)

        first = self.movie.currentPixmap()
        if first.isNull():
            self.movie.jumpToFrame(0)
            first = self.movie.currentPixmap()

        self.image_view.set_pixmap(first)
        self.movie.start()
        self.update_title()
        return True

    def _on_gif_frame(self):
        if self.movie is None:
            return
        pixmap = self.movie.currentPixmap()
        if pixmap.isNull():
            return
        self.image_view.update_pixmap(pixmap)

    def _stop_movie(self):
        if self.movie is None:
            return
        try:
            self.movie.frameChanged.disconnect(self._on_gif_frame)
        except Exception:
            pass
        try:
            self.movie.stop()
        except Exception:
            pass
        self.movie = None

    # ----- 旋转 -----

    def rotate_cw(self):
        if self._is_gif:
            return
        self.rotation = (self.rotation + 90) % 360
        self.show_current()

    def rotate_ccw(self):
        if self._is_gif:
            return
        self.rotation = (self.rotation - 90) % 360
        self.show_current()

    # ----- 键盘 -----

    def keyPressEvent(self, event):
        key = event.key()

        if key in (Qt.Key_Left, Qt.Key_Up, Qt.Key_A, Qt.Key_W):
            self.index = (self.index - 1) % len(self.images)
            self.show_current()
        elif key in (Qt.Key_Right, Qt.Key_Down, Qt.Key_D, Qt.Key_S):
            self.index = (self.index + 1) % len(self.images)
            self.show_current()
        elif key == Qt.Key_F:
            self._toggle_favorite()
        elif key == Qt.Key_Z:
            self.image_view.fit_to_window()
        elif key in (Qt.Key_Plus, Qt.Key_Equal):
            self.image_view.zoom_in()
        elif key == Qt.Key_Minus:
            self.image_view.zoom_out()
        elif key == Qt.Key_Q:
            self.rotate_ccw()
        elif key == Qt.Key_E:
            self.rotate_cw()
        elif key == Qt.Key_Space:
            self.close()
        elif key == Qt.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    def _toggle_favorite(self):
        image_id = self._current_image_id()
        if image_id is None:
            return
        new_state = not database.is_favorite(image_id)
        database.set_favorite(image_id, new_state)
        self.favorite_changed.emit(image_id, new_state)
        self.update_title()

    # ----- 其它 -----

    def open_in_system(self):
        path = self.images[self.index]
        try:
            os.startfile(path)
        except Exception as e:
            print("打开失败：", e)

    def update_title(self):
        path = self.images[self.index]
        name = path.replace("\\", "/").split("/")[-1]
        image_id = self._current_image_id()
        star = "⭐ " if (image_id is not None
                        and database.is_favorite(image_id)) else ""
        gif_mark = " [GIF]" if self._is_gif else ""
        self.setWindowTitle(
            f"{star}{name}{gif_mark} - {self.index + 1} / {len(self.images)}"
        )
   
    def showEvent(self, event):
        super().showEvent(event)
        # 窗口首次显示后，重新适配
        self.image_view.fit_to_window()

    def closeEvent(self, event):
        self._stop_movie()
        self.closed.emit()
        super().closeEvent(event)