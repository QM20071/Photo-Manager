"""
网格项自绘 Delegate。

从 ThumbnailManager 获取缩略图（按 image_id）。
Model 只提供 image_id / 显示文本。

性能约束：
  - 只在 hover / selected 时绘制背景
  - 不绘制白色卡片
  - 不绘制阴影

设计依据：
  《Phase 2B 设计 v2：UI 视觉系统规范》
"""

from PySide6.QtCore import QSize, Qt, QRect
from PySide6.QtGui import QColor, QFontMetrics, QPixmap
from PySide6.QtWidgets import QStyledItemDelegate, QStyle

from ui.theme import get_color


# 网格项尺寸
ICON_SIZE = 160
ITEM_W, ITEM_H = 180, 200

# 圆角
CARD_RADIUS = 8


class ThumbnailDelegate(QStyledItemDelegate):
    """自绘网格项：缩略图居中 + 文件名居中在下方。"""

    def __init__(self, parent=None, thumbnail_manager=None):
        super().__init__(parent)
        self.thumbnail_manager = thumbnail_manager

    def set_thumbnail_manager(self, manager):
        self.thumbnail_manager = manager

    def paint(self, painter, option, index):
        painter.save()

        image_id = index.data(Qt.UserRole)
        full_name = index.data(Qt.UserRole + 1)
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)

        rect = option.rect

        # 只在 hover / selected 时绘制背景（圆角）
        if selected or hovered:
            if selected:
                painter.setBrush(get_color("selected_bg"))
            else:
                painter.setBrush(QColor(0, 0, 0, 18))
            painter.setPen(Qt.NoPen)
            bg_rect = rect.adjusted(2, 2, -2, -2)
            painter.drawRoundedRect(bg_rect, CARD_RADIUS, CARD_RADIUS)

        # 缩略图
        pixmap = None
        file_path = index.data(Qt.UserRole + 3)  # 新增的角色
        if (self.thumbnail_manager is not None
                and image_id is not None
                and file_path):
            pixmap = self.thumbnail_manager.get_cached(image_id)

        if pixmap is not None and not pixmap.isNull():
            pm = pixmap
            if pm.width() != ICON_SIZE or pm.height() != ICON_SIZE:
                pm = pm.scaled(
                    ICON_SIZE, ICON_SIZE,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                )
            icon_x = rect.x() + (rect.width() - pm.width()) // 2
            icon_y = rect.y() + 8
            painter.drawPixmap(icon_x, icon_y, pm)
        else:
            # 占位符
            placeholder = QRect(
                rect.x() + (rect.width() - ICON_SIZE) // 2,
                rect.y() + 8,
                ICON_SIZE, ICON_SIZE
            )
            painter.fillRect(placeholder, QColor(60, 60, 60))

        # 文件名
        if full_name:
            fm = QFontMetrics(option.font)
            text_x = rect.x() + 6
            text_y = rect.y() + 8 + ICON_SIZE + 6
            text_w = rect.width() - 12
            text_h = rect.bottom() - text_y - 4

            if selected:
                painter.setPen(QColor("#FFFFFF"))
            else:
                painter.setPen(get_color("text"))

            single = fm.elidedText(full_name, Qt.ElideRight, text_w)
            painter.drawText(
                QRect(text_x, text_y, text_w, text_h),
                Qt.AlignHCenter | Qt.AlignTop,
                single
            )

        painter.restore()

    def sizeHint(self, option, index):
        return QSize(ITEM_W, ITEM_H)