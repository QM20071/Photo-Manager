"""
ImageListModel：网格的数据模型。

职责：
  - 保存图片的轻量元数据（image_id / file_path / filename / favorite）
  - 为 QListView 提供数据（DisplayRole / UserRole）
  - 提供 get_file_path(image_id) 供 ThumbnailManager 查询
  - 提供 notify_thumbnail_ready(image_id) 触发 View 重绘

关键设计：
  - Model 不持有 QPixmap
  - Model 不返回 QPixmap
  - 缩略图由 ThumbnailManager 管理，Delegate 直接查询

设计依据：
  《Phase 2A 设计：可见区域驱动的缩略图浏览架构》第四节
"""

from dataclasses import dataclass

from PySide6.QtCore import Qt, QAbstractListModel, QModelIndex


@dataclass
class ImageItem:
    """网格中一张图片的元数据。"""
    image_id: int
    file_path: str      # 绝对路径
    filename: str
    favorite: bool = False


class ImageListModel(QAbstractListModel):
    """
    网格数据模型。

    只保存元数据，不保存缩略图。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[ImageItem] = []
        self._id_to_index: dict[int, int] = {}

    # ---------- QAbstractListModel 接口 ----------

    def rowCount(self, parent=QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._items)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = index.row()
        if row < 0 or row >= len(self._items):
            return None

        item = self._items[row]

        if role == Qt.DisplayRole:
            return item.filename

        if role == Qt.UserRole:
            return item.image_id

        if role == Qt.UserRole + 1:
            # 完整显示文本（带 ⭐）
            prefix = "⭐ " if item.favorite else ""
            return prefix + item.filename

        if role == Qt.UserRole + 2:
            return item.favorite
        
        if role == Qt.UserRole + 3:
            return item.file_path
        
        return None

    # ---------- 数据操作 ----------

    def set_images(self, items: list[ImageItem]):
        """替换整个列表。触发 modelReset。"""
        self.beginResetModel()
        self._items = list(items)
        self._id_to_index = {
            item.image_id: i for i, item in enumerate(self._items)
        }
        self.endResetModel()

    def clear(self):
        """清空列表。"""
        self.beginResetModel()
        self._items = []
        self._id_to_index = {}
        self.endResetModel()

    # ---------- 查询 ----------

    def get_file_path(self, image_id: int) -> str | None:
        """根据 image_id 查 file_path。不存在返回 None。"""
        idx = self._id_to_index.get(image_id)
        if idx is None:
            return None
        return self._items[idx].file_path

    def get_item(self, image_id: int) -> ImageItem | None:
        """根据 image_id 查完整 ImageItem。"""
        idx = self._id_to_index.get(image_id)
        if idx is None:
            return None
        return self._items[idx]

    def get_item_at_row(self, row: int) -> ImageItem | None:
        if row < 0 or row >= len(self._items):
            return None
        return self._items[row]

    def all_items(self) -> list[ImageItem]:
        return list(self._items)

    def count(self) -> int:
        return len(self._items)

    # ---------- 缩略图通知 ----------

    def notify_thumbnail_ready(self, image_id: int):
        """通知 View：某个 image_id 的缩略图已就绪，需要重绘。"""
        idx = self._id_to_index.get(image_id)
        if idx is None:
            return
        model_index = self.index(idx, 0)
        self.dataChanged.emit(model_index, model_index)

    def invalidate_thumbnail(self, image_id: int):
        """同 notify_thumbnail_ready，语义上表示"需要重绘"。"""
        self.notify_thumbnail_ready(image_id)

    # ---------- 更新单项 ----------

    def update_favorite(self, image_id: int, favorite: bool):
        """更新收藏状态。"""
        idx = self._id_to_index.get(image_id)
        if idx is None:
            return
        self._items[idx].favorite = favorite
        model_index = self.index(idx, 0)
        self.dataChanged.emit(
            model_index, model_index,
            [Qt.DisplayRole, Qt.UserRole + 1, Qt.UserRole + 2]
        )