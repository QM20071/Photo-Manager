"""
主窗口与启动入口（重构 Step 3：右栏信息面板）。
"""

import sys
import os
import json
import time
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QBoxLayout, QFrame, QStyle,
    QLabel, QPushButton, QFileDialog, QMessageBox,
    QListView, QToolBar, QScrollArea, QInputDialog,
    QDialog, QDialogButtonBox, QMenu, QLineEdit,
    QTextEdit, QAbstractItemView, QDockWidget, QSizePolicy
)
from ui.sidebar import SidebarLeft
from ui.info_panel import InfoPanel
from PySide6.QtCore import QMimeData
from PySide6.QtGui import QDrag
from PySide6.QtCore import (
    Qt, QSize, QEvent, QModelIndex, QTimer, QPoint,
)
from PySide6.QtGui import QPainter, QColor

from send2trash import send2trash

import config
import database
import pinyin
import file_manager
from viewer import ImageViewer
from ui.theme import apply_theme, get_color_str
from core.image_readers import init_image_readers
from PySide6.QtGui import QIcon
from ui.resources import icon
from utils.sorters import sort_albums
from utils.fileops import reveal_in_explorer, open_folder_in_explorer
from core.metadata import (
    get_image_info,
    get_album_info,
    format_size,
    format_time,
    get_exif_info,
    MonthLoader,
)
from core.scanner import (
    ALBUM_NAME_MAX_CHARS,
    list_albums,
    scan_album_folder,
    scan_library_root_loose_files,
    scan_blacklist_folders,
    check_library,
    is_drive_root,
    is_system_dir,
)
from ui.delegate import (
    ICON_SIZE,
    ITEM_W, ITEM_H,
    ThumbnailDelegate,
)
from ui.image_list_model import ImageListModel, ImageItem
from ui.dialogs import (
    DeleteWarningDialog,
    ImportFolderDialog,
    BlacklistDialog,
)
from core.import_worker import ImportWorker
from ui.import_dialog import ImportProgressDialog
from ui.import_history_dialog import ImportHistoryDialog
from core.decode_worker import DecodeWorker
from core.thumbnail_manager import (
    ThumbnailManager,
    PRIORITY_VISIBLE,
    PRIORITY_PREFETCH,
)

SORT_MODES_IMAGE = [
    ("加入时间 ↑", "added_asc"),
    ("加入时间 ↓", "added_desc"),
    ("文件名 ↑",   "name_asc"),
    ("文件名 ↓",   "name_desc"),
    ("修改时间 ↑", "mtime_asc"),
    ("修改时间 ↓", "mtime_desc"),
    ("大小 ↑",     "size_asc"),
    ("大小 ↓",     "size_desc"),
]

SORT_MODES_ALBUM = [
    ("名字 ↑", "name_asc"),
    ("名字 ↓", "name_desc"),
    ("时间 ↑", "mtime_asc"),
    ("时间 ↓", "mtime_desc"),
]

MIME_TYPE = "application/x-photo-image-ids"


class DraggableGrid(QListView):
    """支持拖动图片的网格。手动区分“拖动”和“框选”。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drag_start_pos = None
        self._mouse_pressed = False
        self._selection_snapshot = None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            index = self.indexAt(event.position().toPoint())
            if index.isValid():
                # 按在图片上 → 记录拖动起点
                sel_model = self.selectionModel()
                self._selection_snapshot = list(sel_model.selectedIndexes())
                self._drag_start_pos = event.position().toPoint()
                self._mouse_pressed = True
            else:
                # 按在空白处 → 让 QListView 自己框选
                self._mouse_pressed = False
                self._drag_start_pos = None
                self._selection_snapshot = None

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not self._mouse_pressed:
            super().mouseMoveEvent(event)
            return

        if not (event.buttons() & Qt.LeftButton):
            super().mouseMoveEvent(event)
            return

        current = event.position().toPoint()
        distance = (current - self._drag_start_pos).manhattanLength()

        if distance >= QApplication.startDragDistance():
            self._mouse_pressed = False
            self._start_drag()
            return

        super().mouseMoveEvent(event)
    
    def resizeEvent(self, event):
        super().resizeEvent(event)
        win = self.window()
        if hasattr(win, "_update_visible_range"):
            QTimer.singleShot(50, win._update_visible_range)

    def mouseReleaseEvent(self, event):
        self._mouse_pressed = False
        self._drag_start_pos = None
        self._selection_snapshot = None
        super().mouseReleaseEvent(event)

    def _start_drag(self):
        sel_model = self.selectionModel()
        indexes = sel_model.selectedIndexes()

        # 关键：如果按下时的选中集比现在多，用快照
        # 这样"在已选中的图上按下并拖动"不会丢失其他选中项
        if self._selection_snapshot and len(self._selection_snapshot) > len(indexes):
            indexes = self._selection_snapshot

        if not indexes:
            return

        image_ids = []
        for idx in indexes:
            iid = idx.data(Qt.UserRole)
            if iid is None or iid < 0:
                continue
            image_ids.append(iid)

        if not image_ids:
            return

        mime = QMimeData()
        payload = json.dumps(image_ids).encode("utf-8")
        mime.setData(MIME_TYPE, payload)
        mime.setText(f"{len(image_ids)} 张图片")

        drag = QDrag(self)
        drag.setMimeData(mime)

        pixmap = None
        win = self.window()
        if hasattr(win, "thumbnail_manager"):
            for idx in indexes:
                iid = idx.data(Qt.UserRole)
                if iid is None or iid < 0:
                    continue
                pm = win.thumbnail_manager.get_cached(iid)
                if pm is not None and not pm.isNull():
                    pixmap = pm
                    break

        if pixmap is not None:
            small = pixmap.scaled(
                96, 96, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            drag.setPixmap(small)
            drag.setHotSpot(small.rect().center())

        drag.exec(Qt.MoveAction)

class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("图片管理器 by QM20071")
        self.resize(1400, 900)

        self.current_paths = []
        self.displayed_paths = []
        self.search_query = ""

        self.viewer = None
        self.current_album = None

        self.sort_mode_image = "added_desc"
        self.sort_mode_album = "name_asc"

        self.month_filter = ""
        self._month_map = {}
        self._month_loader = None

        self._saved_selection = []
        self._import_worker = None
        self._import_dialog = None

        # ---------- 工具栏 ----------
        toolbar = QToolBar("主工具栏")
        self.toolbar = toolbar
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.addToolBar(Qt.TopToolBarArea, toolbar)

        def _icon_btn(name, tooltip, callback):
            btn = QPushButton(icon(name), "")
            btn.setProperty("icon_name", name)  
            btn.setToolTip(tooltip)
            btn.setFixedSize(32, 28)
            btn.clicked.connect(callback)
            return btn

        toolbar.addWidget(
            _icon_btn("library", "图库", self.change_library)
        )

        toolbar.addWidget(
            _icon_btn("import", "导入文件夹", self.import_external_folder)
        )

        toolbar.addSeparator()

        # 排序按钮（有菜单）
        self.sort_button = QPushButton(icon("sort"), "")
        self.sort_button.setToolTip("排序")
        self.sort_button.setProperty("icon_name", "sort")
        self.sort_button.setFixedSize(32, 28)
        self.sort_menu = QMenu(self.sort_button)
        self._fill_sort_menu(self.sort_menu, SORT_MODES_IMAGE, "added_desc")
        self.sort_button.clicked.connect(
            lambda: self.sort_menu.exec(
                self.sort_button.mapToGlobal(
                    QPoint(0, self.sort_button.height())
                )
            )
        )
        toolbar.addWidget(self.sort_button)

        # 月份按钮（有菜单）
        self.month_button = QPushButton(icon("month"), "")
        self.month_button.setToolTip("按月份筛选")
        self.month_button.setProperty("icon_name", "month")
        self.month_button.setFixedSize(32, 28)
        self.month_menu = QMenu(self.month_button)
        self.month_button.clicked.connect(
            lambda: self.month_menu.exec(
                self.month_button.mapToGlobal(
                    QPoint(0, self.month_button.height())
                )
            )
        )
        toolbar.addWidget(self.month_button)

        toolbar.addSeparator()

        toolbar.addWidget(
            _icon_btn("refresh", "刷新", self.refresh_current_tab)
        )

        # 图库维护（有菜单）
        btn_maint = QPushButton(icon("maintain"), "")
        btn_maint.setToolTip("图库维护")
        btn_maint.setProperty("icon_name", "maintain")
        btn_maint.setFixedSize(32, 28)
        menu_maint = QMenu(btn_maint)
        menu_maint.addAction("扫描新文件", self.scan_library_root)
        menu_maint.addAction("检查有效性", self.check_library)
        menu_maint.addSeparator()
        menu_maint.addAction("清理失效", self.cleanup_missing)
        menu_maint.addAction("黑名单", self.open_blacklist)
        menu_maint.addSeparator()
        menu_maint.addAction("备份数据库", self.backup_database)
        btn_maint.clicked.connect(
            lambda: menu_maint.exec(
                btn_maint.mapToGlobal(QPoint(0, btn_maint.height()))
            )
        )
        toolbar.addWidget(btn_maint)

        # 更多（有菜单）
        btn_more = QPushButton(icon("more"), "")
        btn_more.setToolTip("更多")
        btn_more.setProperty("icon_name", "more")
        btn_more.setFixedSize(32, 28)
        menu_more = QMenu(btn_more)
        menu_more.addAction("导入历史", self.open_import_history)
        menu_more.addSeparator()
        menu_more.addAction("快捷键", self.show_shortcuts)
        btn_more.clicked.connect(
            lambda: menu_more.exec(
                btn_more.mapToGlobal(QPoint(0, btn_more.height()))
            )
        )
        toolbar.addWidget(btn_more)

        # 删除（红色）
        btn_delete = _icon_btn("delete", "删除", self.delete_action)
        btn_delete.setStyleSheet(
            f"color: {get_color_str('danger')};"
        )
        toolbar.addWidget(btn_delete)

        toolbar.addWidget(
            _icon_btn("undo", "撤销", self.undo_last)
        )

        toolbar.addWidget(
            _icon_btn("new_album", "新建相册", self.create_album)
        )

        # 搜索框 + 清除按钮
        search_widget = QWidget()
        search_layout = QHBoxLayout(search_widget)
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.setSpacing(4)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索文件名（回车）…")
        self.search_edit.setFixedWidth(200)
        self.search_edit.setFixedHeight(28)
        self.search_edit.returnPressed.connect(self.on_search_enter)
        search_layout.addWidget(self.search_edit)

        btn_clear = QPushButton("×")
        btn_clear.setFixedSize(28, 28)
        btn_clear.setProperty("compact", "true")
        btn_clear.clicked.connect(self.clear_search)
        search_layout.addWidget(btn_clear)

        search_widget.setFixedWidth(200 + 4 + 28)
        toolbar.addWidget(search_widget)

        # 弹性空间，把主题按钮推到最右
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        toolbar.addWidget(spacer)

        # 主题切换按钮
        self.theme_button = QPushButton(
            icon("sun" if config.get_theme() == "light" else "moon"), ""
        )
        self.theme_button.setToolTip("切换主题")
        self.theme_button.setFixedSize(32, 28)
        self.theme_button.clicked.connect(self.toggle_theme)
        toolbar.addWidget(self.theme_button)
        # GitHub 按钮
        btn_github = _icon_btn(
            "github", "打开 GitHub 仓库", self._open_github
        )
        toolbar.addWidget(btn_github)

        # ---------- 中央网格 ----------
        self.grid = DraggableGrid()
        self.grid.setMouseTracking(True)
        self.grid.setMovement(QListView.Static)
        self.grid.setDragEnabled(True)
        self.grid.setDragDropMode(QAbstractItemView.DragOnly)
        self.grid.setDefaultDropAction(Qt.MoveAction)
        self.grid.setViewMode(QListView.IconMode)
        self.grid.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self.grid.setResizeMode(QListView.Adjust)
        self.grid.setSpacing(10)
        self.grid.setMovement(QListView.Static)
        self.grid.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.grid.setUniformItemSizes(True)
        self.grid.setStyleSheet(f"""
            QListView {{
                outline: none;
                background-color: {get_color_str('grid_bg')};
            }}
        """)

        self.image_model = ImageListModel(self)
        self.grid.setModel(self.image_model)

        self.decode_worker = DecodeWorker(self)
        self.decode_worker.start()

        self.thumbnail_manager = ThumbnailManager(
            model=self.image_model,
            worker=self.decode_worker,
            max_bytes=100 * 1024 * 1024,
            parent=self,
        )
        self.thumbnail_manager.thumbnail_ready.connect(
            self._on_thumbnail_ready
        )

        self.delegate = ThumbnailDelegate(self.grid, self.thumbnail_manager)
        self.grid.setItemDelegate(self.delegate)

        self.grid.clicked.connect(self.on_item_clicked)
        self.grid.doubleClicked.connect(self.on_grid_double_clicked)
        self.grid.selectionModel().selectionChanged.connect(
            self.on_selection_changed
        )
        self.grid.setContextMenuPolicy(Qt.CustomContextMenu)
        self.grid.customContextMenuRequested.connect(self.on_grid_context_menu)
        self.grid.pressed.connect(self.on_grid_item_pressed)
        self.grid.selectionModel().currentChanged.connect(
            self.on_current_changed
        )
        self.grid.installEventFilter(self)

        self.grid.verticalScrollBar().valueChanged.connect(
            self._on_scroll_changed
        )
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.setInterval(50)
        self._scroll_timer.timeout.connect(self._update_visible_range)

        # ---------- 顶部返回条 + 中央容器 ----------
        self.top_bar = QWidget()
        top_layout = QHBoxLayout(self.top_bar)
        top_layout.setContentsMargins(5, 5, 5, 5)
        top_layout.setSpacing(5)

        self.btn_back = QPushButton("← 返回相册列表")
        self.btn_back.clicked.connect(self._back_to_album_list)
        top_layout.addWidget(self.btn_back)

        self.top_bar.setVisible(False)

        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        central_layout.addWidget(self.top_bar)
        central_layout.addWidget(self.grid, stretch=1)

        self.setCentralWidget(central)

        # ---------- 左侧栏 ----------
        self.sidebar_left = SidebarLeft()
        self.sidebar_left.nav_changed.connect(self._on_sidebar_nav)

        self.left_dock = QDockWidget(self)
        self.left_dock.setObjectName("sidebar_left_dock")
        self.left_dock.setAllowedAreas(
            Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea
        )
        self.left_dock.setFeatures(
            QDockWidget.DockWidgetMovable
            | QDockWidget.DockWidgetFloatable
        )
        self.left_dock.setWidget(self.sidebar_left)
        left_title = QLabel("资源库")
        left_title.setStyleSheet(
            f"padding: 10px 10px 6px 10px;"
            f"font-weight: 500;"
            f"border-bottom: 1px solid {get_color_str('dock_sep')};"
        )
        self.left_dock.setTitleBarWidget(left_title)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.left_dock)
        self.left_dock.setMinimumWidth(180)
        self.left_dock.setMaximumWidth(400)
        self.resizeDocks([self.left_dock], [220], Qt.Horizontal)

        # ---------- 右侧栏 ----------
        self.info_panel = InfoPanel()
        self.right_dock = QDockWidget(self)
        self.right_dock.setObjectName("sidebar_right_dock")
        self.right_dock.setAllowedAreas(
            Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea
        )
        self.right_dock.setFeatures(
            QDockWidget.DockWidgetMovable
            | QDockWidget.DockWidgetFloatable
        )
        self.right_dock.setWidget(self.info_panel)
        right_title = QLabel("信息")
        right_title.setStyleSheet(
            f"padding: 10px 10px 6px 10px;"
            f"font-weight: 500;"
            f"border-bottom: 1px solid {get_color_str('dock_sep')};"
        )
        self.right_dock.setTitleBarWidget(right_title)
        self.addDockWidget(Qt.RightDockWidgetArea, self.right_dock)
        self.right_dock.setMinimumWidth(180)
        self.right_dock.setMaximumWidth(400)
        self.resizeDocks([self.right_dock], [260], Qt.Horizontal)

        # 全局状态文字 → 右栏底部
        self.status_label = self.info_panel.status_label

        # ---------- 初始化 ----------
        self.update_lib_label()
        self.refresh_sidebar_counts()
        self.switch_nav("未整理")

    # ---------- 左栏导航 ----------

    def _on_sidebar_nav(self, nav):
        self.switch_nav(nav)

    def _current_nav_name(self):
        return self.sidebar_left.current_nav()

    def switch_nav(self, nav):
        self.thumbnail_manager.bump_generation()
        self.current_album = None
        self.top_bar.setVisible(False)

        if nav == "未整理":
            self.load_unsorted()
        elif nav == "收藏":
            self.load_favorites()
        elif nav == "相册":
            self.show_album_list()

        self.status_label.setText("")

    def _back_to_album_list(self):
        self.current_album = None
        self.top_bar.setVisible(False)
        self.switch_nav("相册")

    def refresh_sidebar_counts(self):
        try:
            unsorted_count = database.count_unsorted()
        except Exception:
            unsorted_count = 0
        try:
            fav_count = len(database.get_favorites())
        except Exception:
            fav_count = 0
        self.sidebar_left.set_counts(unsorted_count, fav_count)

    # ---------- 相册列表页 ----------

    def show_album_list(self):
        self.current_album = None
        self.top_bar.setVisible(False)

        self.image_model.clear()
        self.current_paths = []
        self.displayed_paths = []
        self.status_label.setText("")

        lib = database.get_library()
        albums = list_albums()
        albums = sort_albums(albums, self.sort_mode_album, lib)

        if not albums:
            self.status_label.setText("还没有相册，去「未整理」里新建一个")
            self._update_info_panel_default()
            return

        album_items = []
        for idx, name in enumerate(albums):
            files = scan_album_folder(name)
            count = len(files)

            cover = database.get_album_cover_manual(name)
            if cover is None or not os.path.exists(cover):
                cover = database.get_album_cover(name)
            if cover is None and files:
                cover = files[0]

            album_items.append(ImageItem(
                image_id=-(idx + 1),
                file_path=cover or "",
                filename=f"{name} ({count})",
                favorite=False,
            ))

        self.image_model.set_images(album_items)
        self.status_label.setText(f"共 {len(albums)} 个相册")

        QTimer.singleShot(100, self._update_visible_range)
        self._update_info_panel_default()

    def enter_album(self, album_name):
        self.thumbnail_manager.bump_generation()

        self.current_album = album_name
        self._fill_sort_menu(
            self.sort_menu, SORT_MODES_IMAGE, self.sort_mode_image
        )
        self.sort_button.setToolTip(
            f"排序：{self._get_sort_label(SORT_MODES_IMAGE, self.sort_mode_image)}"
        )
        self.top_bar.setVisible(True)

        self.sidebar_left.reload_albums()

        lib = database.get_library()
        album_dir = os.path.join(lib, album_name)
        if os.path.isdir(album_dir):
            found_paths = scan_album_folder(album_name)
            records = []
            for real_path in found_paths:
                rel = os.path.relpath(real_path, lib)
                records.append({
                    "storage_type": "managed",
                    "file_path": rel,
                    "organize_status": "sorted",
                    "album_rel_path": album_name,
                })
            if records:
                database.add_images_batch(records)

        self.status_label.setText("正在读取相册...")
        QApplication.processEvents()
        rows = database.get_album_images(album_name)
        rows = self._sort_rows(rows, self.sort_mode_image)

        self.current_paths = rows
        self.displayed_paths = list(rows)

        self.search_query = ""
        self.search_edit.clear()
        self.status_label.setText("")

        self._ensure_month_map(rows)
        self._refresh_month_menu(rows)
        self.month_filter = ""
        self.month_button.setToolTip("按月份筛选")

        self.image_model.clear()

        self.status_label.setText(
            f"相册「{album_name}」：共 {len(rows)} 张"
        )
        self._populate_grid(rows)
        self._update_info_panel_default()

    # ---------- 工具 ----------

    def _row_real_path(self, row):
        return database.get_real_path(row)

    def _row_id(self, index):
        if isinstance(index, QModelIndex):
            if not index.isValid():
                return None
            return index.data(Qt.UserRole)
        return None

    def _compute_db_path(self, real_path):
        lib = database.get_library()
        if lib:
            lib_norm = os.path.normcase(os.path.normpath(lib))
            path_norm = os.path.normcase(os.path.normpath(real_path))
            if path_norm.startswith(lib_norm + os.sep):
                rel = os.path.relpath(real_path, lib)
                return "managed", rel
        return "external", os.path.normpath(real_path)

    # ---------- 缩略图 ----------

    def _on_thumbnail_ready(self, image_id, pixmap):
        self.image_model.notify_thumbnail_ready(image_id)

    def _on_scroll_changed(self, value):
        if hasattr(self, "_scroll_timer"):
            self._scroll_timer.start()

    def _grid_columns(self):
        if self.image_model.count() == 0:
            return 1
        viewport_width = self.grid.viewport().width()
        if viewport_width <= 0:
            return 1
        col_width = ITEM_W + self.grid.spacing()
        if col_width <= 0:
            return 1
        return max(1, viewport_width // col_width)

    def _compute_visible_rows(self):
        total = self.image_model.count()
        if total == 0:
            return []

        viewport_height = self.grid.viewport().height()
        viewport_width = self.grid.viewport().width()

        if viewport_height <= 0 or viewport_width <= 0:
            return []

        scroll_y = self.grid.verticalScrollBar().value()

        tl_index = self.grid.indexAt(QPoint(1, 1))
        br_index = self.grid.indexAt(
            QPoint(viewport_width - 2, viewport_height - 2)
        )

        if not tl_index.isValid() and not br_index.isValid():
            row_height = ITEM_H + self.grid.spacing()
            if row_height <= 0:
                row_height = 200

            columns = self._grid_columns()
            if columns <= 0:
                columns = 1

            first_pixel_row = max(0, scroll_y // row_height - 1)
            last_pixel_row = (scroll_y + viewport_height) // row_height + 1

            first_index = first_pixel_row * columns
            last_index = (last_pixel_row + 1) * columns

            first_index = max(0, min(first_index, total - 1))
            last_index = max(0, min(last_index, total - 1))

            return list(range(first_index, last_index + 1))

        candidate_rows = set()
        for idx in [tl_index, br_index]:
            if idx.isValid():
                candidate_rows.add(idx.row())

        if not candidate_rows:
            return list(range(min(50, total)))

        min_row = min(candidate_rows)
        max_row = max(candidate_rows)
        max_row = min(max_row + self._grid_columns(), total - 1)

        return list(range(min_row, max_row + 1))

    def _update_visible_range(self):
        if self.image_model.count() == 0:
            return
        visible_rows = self._compute_visible_rows()
        
        if not visible_rows:
            return

        visible_ids = []
        for row in visible_rows:
            item = self.image_model.get_item_at_row(row)
            if item is not None:
                visible_ids.append(item.image_id)

        if visible_ids:
            self.thumbnail_manager.request_many(
                visible_ids, PRIORITY_VISIBLE
            )

        prefetch_ids = []
        if visible_rows:
            start = visible_rows[0]
            end = visible_rows[-1]
            N = 15
            total = self.image_model.count()

            for row in range(max(0, start - N), start):
                item = self.image_model.get_item_at_row(row)
                if item is not None:
                    prefetch_ids.append(item.image_id)
            for row in range(end + 1, min(total, end + 1 + N)):
                item = self.image_model.get_item_at_row(row)
                if item is not None:
                    prefetch_ids.append(item.image_id)

        if prefetch_ids:
            self.thumbnail_manager.request_many(
                prefetch_ids, PRIORITY_PREFETCH
            )

    # ---------- 主题 ----------

    def toggle_theme(self):
        labels = {"light": "浅色", "dark": "深色"}

        current = config.get_theme()
        new_theme = "dark" if current == "light" else "light"
        config.set_theme(new_theme)

        # 立即生效（应用级 QSS）
        app = QApplication.instance()
        apply_theme(app, new_theme)

        # 刷新 widget 级样式
        self.grid.setStyleSheet(f"""
            QListView {{
                outline: none;
                background-color: {get_color_str('grid_bg')};
            }}
        """)
        self.grid.viewport().update()

        self.sidebar_left.refresh_theme()
        self.info_panel.refresh_theme()

        # 刷新左栏行的选中/悬停颜色
        self.sidebar_left.update()
        self.sidebar_left._update_selected_style()

        self.status_label.setText(f"主题：{labels[new_theme]}")

        # 重建工具栏图标（颜色随主题变）
        for btn in self.toolbar.findChildren(QPushButton):
            name = btn.property("icon_name")
            if name:
                btn.setIcon(icon(name))

        # 主题按钮换成太阳/月亮
        self.theme_button.setIcon(
            icon("sun" if new_theme == "light" else "moon")
        )

    def _open_github(self):
        import webbrowser
        webbrowser.open("https://github.com/QM20071/Photo-Manager")

    # ---------- 右键选中捕获 ----------

    def on_grid_item_pressed(self, index):
        if not (QApplication.mouseButtons() & Qt.RightButton):
            return
        if not index.isValid():
            return
        selection_model = self.grid.selectionModel()
        if selection_model.isSelected(index):
            self._saved_selection = list(selection_model.selectedIndexes())
        else:
            self._saved_selection = [index]

    # ---------- 菜单项 ----------

    def show_shortcuts(self):
        text = (
            "图片管理器 - 快捷键\n\n"
            "【网格操作】\n"
            "Enter           打开查看器\n"
            "Delete          删除（移到回收站）\n"
            "F2              重命名\n"
            "F               收藏 / 取消收藏\n"
            "R / Ctrl+Z      撤销上一步\n\n"
            "【查看器】\n"
            "← / ↑ / A / W   上一张\n"
            "→ / ↓ / D / S   下一张\n"
            "Z               适应窗口\n"
            "+ / -           放大 / 缩小\n"
            "Q               逆时针旋转 90°\n"
            "E               顺时针旋转 90°\n"
            "F               收藏 / 取消收藏\n"
            "空格            用系统看图打开\n"
            "Esc             关闭查看器\n\n"
            "【其它】\n"
            "F1 / ?          显示本面板\n"
        )
        QMessageBox.information(self, "快捷键", text)

    # ---------- 选中状态 ----------

    def on_selection_changed(self, selected, deselected):
        selection_model = self.grid.selectionModel()
        items = selection_model.selectedIndexes()

        if not items:
            self._update_info_panel_default()
            return

        if len(items) == 1:
            image_id = self._row_id(items[0])

            # 相册封面项（负数 image_id）
            if image_id is not None and image_id < 0:
                display_text = items[0].data(Qt.UserRole + 1) or ""
                if " (" in display_text:
                    album_name = display_text.rsplit(" (", 1)[0]
                    self._show_album_info(album_name)
                else:
                    self._update_info_panel_default()
                return

            if image_id is None:
                self._update_info_panel_default()
                return

            row = database.get_image_by_id(image_id)
            if row is None:
                self._update_info_panel_default()
                return
            real = self._row_real_path(row)
            name = os.path.basename(real)

            if not os.path.exists(real):
                self.info_panel.show_message(
                    name, [("状态", "文件不存在")]
                )
                return

            dim, size_bytes = get_image_info(real)
            mtime = os.path.getmtime(real)

            lines = [
                ("路径", real),
                ("尺寸", dim or "—"),
                ("大小", format_size(size_bytes)),
                ("修改时间", format_time(mtime)),
            ]
            exif = get_exif_info(real)
            for k, v in exif.items():
                lines.append((k, v))
            self.info_panel.show_message(name, lines)

        else:
            total = 0
            for it in items:
                image_id = self._row_id(it)
                if image_id is None or image_id < 0:
                    continue
                row = database.get_image_by_id(image_id)
                if row is None:
                    continue
                real = self._row_real_path(row)
                if os.path.exists(real):
                    try:
                        total += os.path.getsize(real)
                    except OSError:
                        pass
            self.info_panel.show_message(
                "已选中多张",
                [
                    ("数量", f"{len(items)} 张"),
                    ("总大小", format_size(total)),
                ]
            )

    def _update_info_panel_default(self):
        """没选中时，显示当前位置基本信息。"""
        if self.current_album is not None:
            title = self.current_album
            count = len(self.current_paths)
            total = 0
            for r in self.current_paths:
                real = self._row_real_path(r)
                if os.path.exists(real):
                    try:
                        total += os.path.getsize(real)
                    except OSError:
                        pass
            self.info_panel.show_message(
                title,
                [("文件数", f"{count} 张"),
                 ("占用空间", format_size(total))],
            )
            return

        nav = self.sidebar_left.current_nav()
        count = len(self.current_paths)
        total = 0
        for r in self.current_paths:
            real = self._row_real_path(r)
            if os.path.exists(real):
                try:
                    total += os.path.getsize(real)
                except OSError:
                    pass

        if nav == "未整理":
            self.info_panel.show_message(
                "未整理",
                [("文件数", f"{count} 张"),
                 ("占用空间", format_size(total))],
            )
        elif nav == "收藏":
            self.info_panel.show_message(
                "收藏",
                [("文件数", f"{count} 张"),
                 ("占用空间", format_size(total))],
            )
        elif nav == "相册":
            albums = list_albums()
            self.info_panel.show_message(
                "全部相册",
                [("相册数", f"{len(albums)} 个")],
            )
        else:
            self.info_panel.clear()

    def _show_album_info(self, album_name):
        """右栏显示一个相册的信息。"""
        lib = database.get_library()
        folder = os.path.join(lib, album_name)
        count = 0
        total = 0
        if os.path.isdir(folder):
            from core.scanner import IMAGE_EXTS
            for root, _, files in os.walk(folder):
                for f in files:
                    if os.path.splitext(f)[1].lower() in IMAGE_EXTS:
                        count += 1
                        try:
                            total += os.path.getsize(os.path.join(root, f))
                        except OSError:
                            pass

        self.info_panel.show_message(
            album_name,
            [
                ("文件数", f"{count} 张"),
                ("占用空间", format_size(total)),
            ],
        )

    # ---------- 排序 / 月份 ----------

    def _fill_sort_menu(self, menu, modes, current_mode):
        menu.clear()
        for label, mode in modes:
            action = menu.addAction(label)
            action.setData(mode)
            action.setCheckable(True)
            action.setChecked(mode == current_mode)
            action.triggered.connect(
                lambda checked, m=mode: self._on_sort_selected(m)
            )

    def _get_sort_label(self, modes, mode):
        for label, m in modes:
            if m == mode:
                return label
        return "排序"

    def _on_sort_selected(self, mode):
        self.sort_mode_image = mode

        for label, m in SORT_MODES_IMAGE:
            if m == mode:
                self.sort_button.setToolTip(f"排序：{label}")
                break

        self._fill_sort_menu(self.sort_menu, SORT_MODES_IMAGE, mode)
        self.refresh_current_tab()

    def _ensure_month_map(self, rows):
        if not rows:
            return

        image_ids = [r["id"] for r in rows]

        try:
            db_months = database.get_image_months(image_ids)
        except Exception:
            db_months = {i: None for i in image_ids}

        id_to_real = {}
        for r in rows:
            id_to_real[r["id"]] = self._row_real_path(r)

        to_read = []
        for image_id in image_ids:
            m = db_months.get(image_id)
            if m:
                self._month_map[image_id] = m
            else:
                real = id_to_real.get(image_id)
                if real:
                    to_read.append((image_id, real))

        if not to_read:
            return

        self.status_label.setText(f"正在读取日期信息 0 / {len(to_read)}...")

        if getattr(self, "_month_loader", None) is not None \
                and self._month_loader.isRunning():
            self._month_loader.stop()
            self._month_loader.wait()

        path_to_id = {p: i for (i, p) in to_read}
        real_paths = [p for (_, p) in to_read]

        self._month_loader = MonthLoader(real_paths)
        self._month_loader.month_ready.connect(
            lambda batch: self._on_month_batch_with_map(batch, path_to_id)
        )
        self._month_loader.finished_all.connect(self._on_month_done)
        self._month_loader.start()

    def _on_month_batch_with_map(self, batch, path_to_id):
        for path, month in batch:
            image_id = path_to_id.get(path)
            if image_id is None:
                continue
            self._month_map[image_id] = month
            try:
                database.set_image_month(image_id, month)
            except Exception:
                pass

        done = len(self._month_map)
        self.status_label.setText(f"已读取 {done} 张的日期信息...")

    def _on_month_done(self):
        self._refresh_month_menu(self.current_paths)
        self.status_label.setText(
            f"日期信息读取完成   |   共 {len(self.current_paths)} 张"
        )

    def _refresh_month_menu(self, rows):
        months = set()
        for r in rows:
            m = self._month_map.get(r["id"])
            if m and m != "未知":
                months.add(m)

        sorted_months = sorted(months, reverse=True)
        current = self.month_filter

        self.month_menu.clear()

        act_all = self.month_menu.addAction("全部")
        act_all.setData("")
        act_all.setCheckable(True)
        act_all.setChecked(not current)
        act_all.triggered.connect(
            lambda: self._on_month_selected("")
        )

        for m in sorted_months:
            act = self.month_menu.addAction(m)
            act.setData(m)
            act.setCheckable(True)
            act.setChecked(m == current)
            act.triggered.connect(
                lambda checked, mm=m: self._on_month_selected(mm)
            )

        if current:
            self.month_button.setToolTip(f"按月份筛选：{current}")
        else:
            self.month_button.setToolTip("按月份筛选")

    def _on_month_selected(self, month):
        self.month_filter = month or ""

        if month:
            self.month_button.setToolTip(f"按月份筛选：{month}")
        else:
            self.month_button.setToolTip("按月份筛选")

        self._refresh_month_menu(self.current_paths)
        self._apply_month_filter()

    def _apply_month_filter(self):
        if not self.month_filter:
            filtered = list(self.current_paths)
        else:
            filtered = [r for r in self.current_paths
                        if self._month_map.get(r["id"]) == self.month_filter]

        self.displayed_paths = filtered
        self.image_model.clear()
        self.status_label.setText("")

        label = f"月份：{self.month_filter}" if self.month_filter else "全部"
        self.status_label.setText(f"{label}   |   {len(filtered)} 张")

        self._populate_grid(filtered)

    # ---------- 搜索 ----------

    def on_search_enter(self):
        self.search_query = self.search_edit.text().strip()
        self.apply_search()

    def clear_search(self):
        self.search_edit.clear()
        self.search_query = ""
        self.apply_search()

    def apply_search(self):
        if not self.search_query:
            filtered = list(self.current_paths)
        else:
            def _match(row):
                real = self._row_real_path(row)
                name = os.path.basename(real)
                return pinyin.match(name, self.search_query)
            filtered = [r for r in self.current_paths if _match(r)]

        self.displayed_paths = filtered
        self.image_model.clear()
        self.status_label.setText("")
        self.status_label.setText(
            f"共 {len(filtered)} 张（原始 {len(self.current_paths)}）"
        )

        self._populate_grid(filtered)

    def _populate_grid(self, rows):
        total = len(rows)
        items = []

        BATCH = 1000
        for i, r in enumerate(rows):
            real_path = self._row_real_path(r)
            items.append(ImageItem(
                image_id=r["id"],
                file_path=real_path,
                filename=os.path.basename(real_path),
                favorite=bool(r.get("favorite")),
            ))

            if (i + 1) % BATCH == 0:
                self.status_label.setText(
                    f"正在创建列表 {i + 1} / {total}..."
                )
                QApplication.processEvents()

        self.image_model.set_images(items)
        QTimer.singleShot(300, self._update_visible_range)
        QTimer.singleShot(800, self._update_visible_range)

    # ---------- 扫描图库 / 导入文件夹 ----------

    def scan_library_root(self):
        lib = database.get_library()
        if not lib or not os.path.isdir(lib):
            QMessageBox.warning(self, "错误", "图库路径无效")
            return

        reply = QMessageBox.question(
            self, "扫描新文件",
            "将扫描图库根目录和黑名单文件夹，把新发现的图片登记到数据库。\n"
            "不会移动任何文件。\n\n继续吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )
        if reply != QMessageBox.Yes:
            return

        self.status_label.setText("正在扫描图库...")
        QApplication.processEvents()

        found_paths = []
        found_paths.extend(scan_library_root_loose_files())
        found_paths.extend(scan_blacklist_folders())

        records = []
        for real_path in found_paths:
            rel = os.path.relpath(real_path, lib)
            records.append({
                "storage_type": "managed",
                "file_path": rel,
                "organize_status": "unsorted",
                "album_rel_path": None,
            })

        new_ids, skip = database.add_images_batch(records)

        self.status_label.setText(
            f"扫描完成：发现 {len(found_paths)} 张，"
            f"新增 {len(new_ids)} 张，跳过 {skip} 张"
        )

        self.load_unsorted()

    def import_external_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, "选择要导入的文件夹（图库外部）"
        )
        if not folder:
            return

        result, message = _validate_import_path(folder)
        if result == "reject":
            QMessageBox.warning(self, "不允许", message)
            return
        if result == "warn":
            reply = QMessageBox.warning(
                self, "警告", message,
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return

        self._run_import(folder)

    def _run_import(self, folder):
        if self._import_worker is not None:
            return

        worker = ImportWorker(folder, parent=self)
        dlg = ImportProgressDialog(folder, worker, parent=self)

        self._import_worker = worker
        self._import_dialog = dlg

        worker.start()
        dlg.exec()

        self._import_dialog = None
        self._import_worker = None

        self.load_unsorted()

    # ---------- 清理 / 检查 ----------

    def cleanup_missing(self):
        reply = QMessageBox.question(
            self, "清理失效记录",
            "将删除数据库中所有「文件已不存在」的图片记录，"
            "并清理对应的缩略图缓存。\n"
            "此操作不影响磁盘上的任何图片文件。\n\n确定继续吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        rows = database.get_all_images()
        total = len(rows)

        removed = 0
        cache_removed = 0
        freed_bytes = 0

        from core.decode_worker import cache_path_for as _cache_path_for

        for row in rows:
            real = self._row_real_path(row)
            if not os.path.exists(real):
                database.delete_image_record(row["id"])
                removed += 1
                try:
                    cf = _cache_path_for(real)
                    if cf and os.path.exists(cf):
                        sz = os.path.getsize(cf)
                        os.remove(cf)
                        cache_removed += 1
                        freed_bytes += sz
                except Exception:
                    pass

        QMessageBox.information(
            self, "清理完成",
            f"数据库记录：{total} 条\n"
            f"失效记录：{removed} 条\n"
            f"清理缩略图缓存：{cache_removed} 个\n"
            f"释放空间：{format_size(freed_bytes)}"
        )
        self.status_label.setText(
            f"清理完成：{removed} 条失效记录，释放 "
            f"{format_size(freed_bytes)}"
        )
        self.refresh_current_tab()

    def check_library(self):
        rows = database.get_all_images()
        total = len(rows)

        if total == 0:
            QMessageBox.information(self, "检查有效性", "数据库里没有记录")
            return

        self.status_label.setText(f"正在检查 {total} 条记录...")
        QApplication.processEvents()

        result = check_library()

        self.status_label.setText("检查完成")

        lines = [
            f"数据库记录：{result['total']} 张",
            f"可读：{result['available']} 张",
            f"缺失：{result['missing']} 张",
            f"损坏：{result['unreadable']} 张",
            f"状态变化：{result['changed']} 张",
        ]

        dlg = QDialog(self)
        dlg.setWindowTitle("检查有效性")
        dlg.resize(500, 300)

        layout = QVBoxLayout(dlg)
        te = QTextEdit()
        te.setReadOnly(True)
        te.setPlainText("\n".join(lines))
        layout.addWidget(te)

        btns = QDialogButtonBox(QDialogButtonBox.Ok)
        btns.accepted.connect(dlg.accept)
        layout.addWidget(btns)

        dlg.exec()
        self.refresh_current_tab()

    def backup_database(self):
        ok, result = database.backup_database(keep=5)
        if not ok:
            QMessageBox.warning(self, "备份失败", result)
            return

        name = os.path.basename(result)
        QMessageBox.information(
            self, "备份完成",
            f"已备份数据库：\n{name}\n\n位置：data\\backup\\\n"
            f"（保留最近 5 份）"
        )
        self.status_label.setText(f"已备份数据库：{name}")

    # ---------- 键盘事件 ----------

    def eventFilter(self, obj, event):
        if obj is self.grid:
            if event.type() == QEvent.KeyPress:
                if (event.key() == Qt.Key_R
                        and not (event.modifiers() & Qt.ControlModifier)):
                    self.undo_last()
                    return True
                if (event.key() == Qt.Key_Z
                        and (event.modifiers() & Qt.ControlModifier)):
                    self.undo_last()
                    return True

                if event.key() == Qt.Key_F1:
                    self.show_shortcuts()
                    return True

                if event.key() == Qt.Key_F:
                    self.toggle_favorite_selected()
                    return True

                if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                    index = self.grid.currentIndex()
                    if index.isValid():
                        self.open_viewer_for_item(index)
                    return True

                if event.key() == Qt.Key_Delete:
                    self.delete_with_first_warning()
                    return True

                if event.key() == Qt.Key_F2:
                    self.rename_selected()
                    return True

                if event.key() == Qt.Key_Space:
                    if self.viewer is not None:
                        self.viewer.close()
                        return True
                    items = self.grid.selectionModel().selectedIndexes()
                    if len(items) == 1:
                        self.open_viewer_for_item(items[0])
                    return True

        return super().eventFilter(obj, event)

    # ---------- 图库 / 黑名单 ----------

    def update_lib_label(self):
        lib = database.get_library()
        if lib:
            self.setWindowTitle(f"图片管理器 by QM20071   -   {lib}")
        else:
            self.setWindowTitle("图片管理器 by QM20071")

    def change_library(self):
        folder = QFileDialog.getExistingDirectory(self, "选择或新建总图库文件夹")
        if not folder:
            return
        config.set_library_path(folder)
        database.set_library(folder)
        database.init_db()
        self.update_lib_label()
        self._month_map = {}
        self.load_unsorted()

    def open_blacklist(self):
        dlg = BlacklistDialog(self)
        dlg.exec()
        self.refresh_current_tab()

    def open_import_history(self):
        dlg = ImportHistoryDialog(self)
        dlg.exec()

        reimport_path = dlg.get_reimport_path()
        if reimport_path:
            result, message = _validate_import_path(reimport_path)
            if result == "reject":
                QMessageBox.warning(self, "不允许", message)
                return
            if result == "warn":
                reply = QMessageBox.warning(
                    self, "警告", message,
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No
                )
                if reply != QMessageBox.Yes:
                    return
            self._run_import(reimport_path)
            return

        if dlg.need_refresh_main():
            self.load_unsorted()

    def closeEvent(self, event):
        if self._import_worker is not None:
            if self._import_worker.isRunning():
                self._import_worker.cancel()
                self._import_worker.wait()

        if self.decode_worker is not None and self.decode_worker.isRunning():
            self.decode_worker.stop()
            self.decode_worker.wait()
        event.accept()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_scroll_timer"):
            self._scroll_timer.start()

    # ---------- 删除 / 收藏 ----------

    def delete_action(self):
        """工具栏"删除"按钮：删除当前选中项。"""
        nav = self.sidebar_left.current_nav()
        if nav == "相册" and self.current_album is None:
            selection_model = self.grid.selectionModel()
            items = selection_model.selectedIndexes()

            index = None
            if items:
                index = items[0]
            else:
                ci = self.grid.currentIndex()
                if ci.isValid():
                    index = ci

            if index is not None:
                image_id = index.data(Qt.UserRole)
                if image_id is not None and image_id < 0:
                    display_text = index.data(Qt.UserRole + 1) or ""
                    if " (" in display_text:
                        album_name = display_text.rsplit(" (", 1)[0]
                        if album_name in list_albums():
                            self.delete_album(album_name)
                            return

            QMessageBox.information(self, "未选中", "请先选中一个相册")
            return

        items = self.grid.selectionModel().selectedIndexes()
        if not items:
            QMessageBox.information(self, "未选中", "请先选中至少一张图片")
            return

        self.delete_with_first_warning()

    def create_album(self):
        name, ok = QInputDialog.getText(
            self, "新建相册",
            f"相册名称（最多 {ALBUM_NAME_MAX_CHARS} 字符）："
        )
        if not ok or not name.strip():
            return
        name = name.strip()
        if len(name) > ALBUM_NAME_MAX_CHARS:
            QMessageBox.warning(self, "太长",
                                f"相册名不能超过 {ALBUM_NAME_MAX_CHARS} 字符")
            return
        lib = database.get_library()
        folder = os.path.join(lib, name)
        if os.path.exists(folder):
            QMessageBox.warning(self, "已存在", f"相册「{name}」已存在")
            return
        try:
            os.makedirs(folder)
        except Exception as e:
            QMessageBox.warning(self, "失败", str(e))
            return
        self.sidebar_left.reload_albums()
        self.refresh_sidebar_counts()

    def delete_album(self, album_name):
        reply = QMessageBox.question(
            self, "删除相册",
            f"确定要把相册「{album_name}」整个移到 Windows 回收站吗？\n"
            f"（里面的所有图片会一起进入回收站）",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        lib = database.get_library()
        folder = os.path.join(lib, album_name)

        folder_abs = os.path.normcase(os.path.abspath(folder))
        lib_abs = os.path.normcase(os.path.abspath(lib))
        if folder_abs == lib_abs:
            QMessageBox.warning(self, "错误", "不能删除图库根目录")
            return
        if not folder_abs.startswith(lib_abs + os.sep):
            QMessageBox.warning(self, "错误", "非法的相册路径")
            return

        if not os.path.isdir(folder):
            QMessageBox.warning(self, "错误", "相册文件夹不存在")
            return

        try:
            send2trash(os.path.normpath(folder))
        except Exception as e:
            QMessageBox.warning(self, "删除失败", str(e))
            return

        database.delete_album_records(album_name)
        database.delete_album_cover(album_name)
        self.sidebar_left.reload_albums()
        self.refresh_sidebar_counts()
        self.show_album_list()
        self.status_label.setText(f"已删除相册「{album_name}」到回收站")

    def delete_with_first_warning(self):
        if not config.get_delete_warned():
            dlg = DeleteWarningDialog(self)
            dlg.exec()
            config.set_delete_warned()
        self.delete_selected()

    def toggle_favorite_selected(self):
        items = self.grid.selectionModel().selectedIndexes()
        if not items:
            return

        all_fav = True
        for it in items:
            image_id = self._row_id(it)
            if image_id is None or image_id < 0:
                continue
            if not database.is_favorite(image_id):
                all_fav = False
                break

        new_state = not all_fav

        for it in items:
            image_id = self._row_id(it)
            if image_id is None or image_id < 0:
                continue
            database.set_favorite(image_id, new_state)
            self.image_model.update_favorite(image_id, new_state)

        self.grid.viewport().update()

        if new_state:
            self.status_label.setText(f"已收藏 {len(items)} 张")
        else:
            self.status_label.setText(f"已取消收藏 {len(items)} 张")

    # ---------- 重命名 ----------

    def rename_selected(self):
        items = self.grid.selectionModel().selectedIndexes()
        if not items:
            QMessageBox.information(self, "未选中", "请先选中一张图片")
            return
        if len(items) > 1:
            QMessageBox.information(self, "只支持单张", "一次只能重命名一张图片")
            return

        index = items[0]
        image_id = self._row_id(index)
        if image_id is None or image_id < 0:
            return
        row = database.get_image_by_id(image_id)
        if row is None:
            QMessageBox.warning(self, "错误", "图片记录不存在")
            return

        real = self._row_real_path(row)
        if not os.path.exists(real):
            QMessageBox.warning(self, "文件不存在", real)
            return

        old_name = os.path.basename(real)
        old_main, ext = os.path.splitext(old_name)

        new_main, ok = QInputDialog.getText(
            self, "重命名图片",
            f"输入新名称（扩展名保持 {ext}）：",
            text=old_main
        )
        if not ok:
            return
        new_main = new_main.strip()
        if not new_main or new_main == old_main:
            return

        result, info = file_manager.rename_file(image_id, real, new_main)
        if result == file_manager.RESULT_FAILED:
            QMessageBox.warning(self, "重命名失败", info)
            return

        new_real = info

        new_row = database.get_image_by_id(image_id)
        new_filename = os.path.basename(new_real)
        new_favorite = bool(new_row.get("favorite")) if new_row else False

        current_items = self.image_model.all_items()
        for i, item in enumerate(current_items):
            if item.image_id == image_id:
                current_items[i] = ImageItem(
                    image_id=image_id,
                    file_path=new_real,
                    filename=new_filename,
                    favorite=new_favorite,
                )
                break
        self.image_model.set_images(current_items)

        self.status_label.setText(
            f"已重命名：{old_name} → {new_filename}"
        )

    # ---------- 删除 ----------

    def delete_selected(self):
        items = self.grid.selectionModel().selectedIndexes()
        if not items:
            QMessageBox.information(self, "未选中", "请先选中至少一张图片")
            return

        pairs = []
        for index in items:
            image_id = self._row_id(index)
            if image_id is None or image_id < 0:
                continue
            row = database.get_image_by_id(image_id)
            if row is None:
                continue
            real = self._row_real_path(row)
            pairs.append((image_id, real))

        if not pairs:
            return

        deleted, failed = file_manager.delete_files(pairs)

        deleted_ids = set([i for i, _ in deleted])

        remaining_items = [
            item for item in self.image_model.all_items()
            if item.image_id not in deleted_ids
        ]
        self.image_model.set_images(remaining_items)

        self.current_paths = [r for r in self.current_paths
                              if r["id"] not in deleted_ids]
        self.displayed_paths = [r for r in self.displayed_paths
                                if r["id"] not in deleted_ids]

        msg = f"已删除 {len(deleted)} 张到回收站，可在系统回收站还原"
        if failed:
            msg += f"，{len(failed)} 张失败"
        self.status_label.setText(msg)

    # ---------- 撤销 ----------

    def undo_last(self):
        op = database.pop_last_operation()
        if op is None:
            QMessageBox.information(self, "撤销", "没有可撤销的操作")
            return

        if op["op_type"] != "move":
            QMessageBox.information(
                self, "撤销", f"暂不支持撤销 {op['op_type']} 操作"
            )
            return

        def parse_paths(s):
            if s is None:
                return []
            try:
                obj = json.loads(s)
                if isinstance(obj, list):
                    return obj
                return [s]
            except Exception:
                return [s]

        srcs = parse_paths(op["src_path"])
        dsts = parse_paths(op["dst_path"])

        if not srcs or len(srcs) != len(dsts):
            QMessageBox.warning(self, "撤销失败", "操作历史数据异常，无法撤销")
            return

        pairs = list(zip(srcs, dsts))
        pairs.reverse()

        ok_count = 0
        fail_count = 0
        partial_count = 0
        error_msgs = []

        for src, dst in pairs:
            try:
                if not os.path.exists(dst):
                    fail_count += 1
                    error_msgs.append(f"目标不存在：{dst}")
                    continue

                storage_type, db_path = self._compute_db_path(dst)
                row = database.get_image_by_path(db_path, storage_type)
                if row is None:
                    fail_count += 1
                    error_msgs.append(f"数据库找不到记录：{dst}")
                    continue

                image_id = row["id"]

                target = src
                if os.path.exists(target):
                    src_dir = os.path.dirname(src)
                    os.makedirs(src_dir, exist_ok=True)

                    base = os.path.basename(src)
                    name, ext = os.path.splitext(base)
                    counter = 1
                    while os.path.exists(target):
                        target = os.path.join(
                            src_dir, f"{name}_undo({counter}){ext}"
                        )
                        counter += 1
                else:
                    src_dir = os.path.dirname(src)
                    os.makedirs(src_dir, exist_ok=True)

                result, info = file_manager.move_to_exact_path(
                    image_id, dst, target
                )

                if result == file_manager.RESULT_SUCCESS:
                    ok_count += 1
                elif result == file_manager.RESULT_PARTIAL:
                    partial_count += 1
                    error_msgs.append(f"部分成功：{info}")
                else:
                    fail_count += 1
                    error_msgs.append(f"失败：{info}")

            except Exception as e:
                fail_count += 1
                error_msgs.append(f"异常：{e}")

        try:
            self.refresh_current_tab()
        except Exception:
            pass

        try:
            self.refresh_sidebar_counts()
            self.sidebar_left.reload_albums()
        except Exception:
            pass

        msg = f"已撤销 {ok_count} 张"
        if partial_count:
            msg += f"，{partial_count} 张部分成功"
        if fail_count:
            msg += f"，{fail_count} 张失败"
        self.status_label.setText(msg)

        if error_msgs:
            QMessageBox.warning(
                self, "撤销详情",
                msg + "\n\n" + "\n".join(error_msgs[:10])
            )

    # ---------- 刷新 / 加载 ----------

    def refresh_current_tab(self):
        if config.is_safe_mode():
            config.set_safe_mode(False)

        self._scan_library_root_loose_files_quick()
        self.refresh_sidebar_counts()

        nav = self.sidebar_left.current_nav()
        if nav == "未整理":
            self.load_unsorted()
        elif nav == "收藏":
            self.load_favorites()
        elif nav == "相册":
            if self.current_album is None:
                self.show_album_list()
            else:
                self.enter_album(self.current_album)

    def _scan_library_root_loose_files_quick(self):
        lib = database.get_library()
        if not lib or not os.path.isdir(lib):
            return

        try:
            found_paths = scan_library_root_loose_files()
        except Exception:
            return

        records = []
        for real_path in found_paths:
            rel = os.path.relpath(real_path, lib)
            records.append({
                "storage_type": "managed",
                "file_path": rel,
                "organize_status": "unsorted",
                "album_rel_path": None,
            })

        if records:
            database.add_images_batch(records)

    def load_unsorted(self):
        self.status_label.setText("正在读取数据库...")
        QApplication.processEvents()
        rows = database.get_unsorted_images()
        self._load_rows(rows, "未整理")
        self._update_info_panel_default()

    def load_favorites(self):
        self.status_label.setText("正在读取数据库...")
        QApplication.processEvents()
        rows = database.get_favorites()
        self._load_rows(rows, "收藏")
        self._update_info_panel_default()

    def _load_rows(self, rows, tab_name):
        total = len(rows)

        self.status_label.setText(f"{tab_name}：正在排序 {total} 条...")
        QApplication.processEvents()
        rows = self._sort_rows(rows, self.sort_mode_image)

        self.current_paths = rows
        self.displayed_paths = list(rows)

        self.search_query = ""
        self.search_edit.clear()
        self.status_label.setText("")

        self.status_label.setText(f"{tab_name}：正在读取日期信息...")
        QApplication.processEvents()
        self._ensure_month_map(rows)
        self._refresh_month_menu(rows)
        self.month_filter = ""
        self.month_button.setToolTip("按月份筛选")

        self.image_model.clear()
        self._populate_grid(rows)

        self.status_label.setText("")

    def _sort_rows(self, rows, mode):
        def _mtime(row):
            real = self._row_real_path(row)
            try:
                return os.path.getmtime(real)
            except OSError:
                return 0

        def _size(row):
            real = self._row_real_path(row)
            try:
                return os.path.getsize(real)
            except OSError:
                return 0

        def _name(row):
            real = self._row_real_path(row)
            return os.path.basename(real).lower()

        if mode == "added_asc":
            return list(rows)
        elif mode == "added_desc":
            return list(reversed(rows))
        elif mode == "name_asc":
            return sorted(rows, key=_name)
        elif mode == "name_desc":
            return sorted(rows, key=_name, reverse=True)
        elif mode == "mtime_asc":
            return sorted(rows, key=_mtime)
        elif mode == "mtime_desc":
            return sorted(rows, key=_mtime, reverse=True)
        elif mode == "size_asc":
            return sorted(rows, key=_size)
        elif mode == "size_desc":
            return sorted(rows, key=_size, reverse=True)
        return list(rows)

    # ---------- 网格事件 ----------

    def on_grid_double_clicked(self, index):
        if not index.isValid():
            return

        image_id = index.data(Qt.UserRole)

        # 相册封面项（负数 id）→ 进相册
        if image_id is not None and image_id < 0:
            display_text = index.data(Qt.UserRole + 1) or ""
            if " (" in display_text:
                album_name = display_text.rsplit(" (", 1)[0]
                self.enter_album(album_name)
            return

        # 普通图片 → 打开查看器
        self.open_viewer_for_item(index)

    def open_viewer_for_item(self, index):
        if not self.displayed_paths:
            return
        if not index.isValid():
            return
        image_id = self._row_id(index)
        if image_id is None or image_id < 0:
            return
        row_index = None
        for i, r in enumerate(self.displayed_paths):
            if r["id"] == image_id:
                row_index = i
                break
        if row_index is None:
            return

        real_paths = [self._row_real_path(r) for r in self.displayed_paths]
        self.viewer = ImageViewer(real_paths, row_index)
        self.viewer.favorite_changed.connect(
            self._on_viewer_favorite_changed
        )
        self.viewer.closed.connect(self._on_viewer_closed)
        self.viewer.show()
        self.viewer.destroyed.connect(self._on_viewer_closed)
    
    def _on_viewer_closed(self):
        self.viewer = None

    def _on_viewer_favorite_changed(self, image_id, favorite):
        self.image_model.update_favorite(image_id, favorite)
        self.grid.viewport().update()

    def handle_drop_on_sidebar(self, target, image_ids, album_name):
        """
        target: "未整理" / "收藏" / "album"
        image_ids: list[int]
        album_name: 目标相册名（target == "album" 时有效）
        """
        if not image_ids:
            return

        if target == "收藏":
            # 只要有一张已收藏 → 全部取消；否则全部收藏
            any_fav = any(database.is_favorite(iid) for iid in image_ids)
            new_state = not any_fav

            for iid in image_ids:
                database.set_favorite(iid, new_state)
                self.image_model.update_favorite(iid, new_state)
            self.grid.viewport().update()
            self.refresh_sidebar_counts()
            self.sidebar_left.reload_albums()

            if new_state:
                self.status_label.setText(f"已收藏 {len(image_ids)} 张")
            else:
                self.status_label.setText(f"已取消收藏 {len(image_ids)} 张")
            return

        if target == "未整理":
            self._move_images_to_album(image_ids, None)
            return

        if target == "album" and album_name:
            self._move_images_to_album(image_ids, album_name)
            return

    def _move_images_to_album(self, image_ids, album_name):
        """
        album_name=None → 移到图库根目录（未整理）
        album_name="xxx" → 移到图库/xxx
        """
        lib = database.get_library()
        if not lib:
            return

        if album_name is None:
            dst_dir = lib
        else:
            dst_dir = os.path.join(lib, album_name)

        pairs = []
        for iid in image_ids:
            row = database.get_image_by_id(iid)
            if row is None:
                continue
            real = self._row_real_path(row)
            if not os.path.exists(real):
                continue
            # 已在目标目录里 → 跳过
            try:
                if os.path.normcase(os.path.dirname(real)) == \
                        os.path.normcase(dst_dir):
                    continue
            except Exception:
                pass
            pairs.append((iid, real))

        if not pairs:
            self.status_label.setText("无需移动")
            return

        success, partial, failed = file_manager.move_files(
            pairs, dst_dir
        )

        moved_ids = set([i for i, _ in success])
        remaining_items = [
            item for item in self.image_model.all_items()
            if item.image_id not in moved_ids
        ]
        self.image_model.set_images(remaining_items)

        self.current_paths = [r for r in self.current_paths
                              if r["id"] not in moved_ids]
        self.displayed_paths = [r for r in self.displayed_paths
                                if r["id"] not in moved_ids]

        msg = f"已移动 {len(success)} 张"
        if album_name:
            msg += f"到相册「{album_name}」"
        else:
            msg += "到未整理"
        if partial:
            msg += f"，{len(partial)} 张部分成功"
        if failed:
            msg += f"，{len(failed)} 张失败"
        self.status_label.setText(msg)

        self.refresh_sidebar_counts()
        self.sidebar_left.reload_albums()
        self._update_info_panel_default()

    def on_item_clicked(self, index):
        pass

    def on_current_changed(self, current, previous):
        pass

    # ---------- 右键菜单 ----------

    def on_grid_context_menu(self, pos):
        index = self.grid.indexAt(pos)
        if not index.isValid():
            return

        image_id = self._row_id(index)
        if image_id is None or image_id < 0:
            return

        row = database.get_image_by_id(image_id)
        if row is None:
            return
        real = self._row_real_path(row)

        saved = self._saved_selection if self._saved_selection else [index]

        all_fav = True
        for it in saved:
            iid = self._row_id(it)
            if iid is None or iid < 0 or not database.is_favorite(iid):
                all_fav = False
                break

        menu = QMenu(self)
        act_open_sys = menu.addAction("用系统看图打开")
        act_reveal = menu.addAction("打开文件所在位置")
        act_rename = menu.addAction("重命名")
        act_fav = menu.addAction("取消收藏" if all_fav else "收藏")

        menu.addSeparator()
        act_delete = menu.addAction("删除")

        chosen = menu.exec(self.grid.mapToGlobal(pos))
        if chosen is None:
            return
        
        if chosen == act_open_sys:
            try:
                os.startfile(real)
            except Exception as e:
                QMessageBox.warning(self, "打开失败", str(e))
        elif chosen == act_reveal:
            ok = reveal_in_explorer(real)
            if not ok:
                QMessageBox.warning(
                    self, "失败",
                    f"文件不存在或无法打开：\n{real}"
                )
        elif chosen == act_rename:
            self.rename_selected()
        elif chosen == act_fav:
            new_state = not all_fav
            for it in saved:
                iid = self._row_id(it)
                if iid is None or iid < 0:
                    continue
                database.set_favorite(iid, new_state)
                self.image_model.update_favorite(iid, new_state)
            self.grid.viewport().update()
            if new_state:
                self.status_label.setText(f"已收藏 {len(saved)} 张")
            else:
                self.status_label.setText(f"已取消收藏 {len(saved)} 张")
        elif chosen == act_delete:
            self.delete_with_first_warning()


# ---------- 启动 ----------

def _validate_import_path(folder):
    folder = os.path.normpath(os.path.abspath(folder))

    if not os.path.isdir(folder):
        return "reject", f"文件夹不存在：\n{folder}"

    if is_drive_root(folder):
        return "reject", (
            f"不能导入整个磁盘根目录：\n{folder}\n\n"
            "请选择一个具体的子文件夹。"
        )

    lib = database.get_library()
    if lib:
        lib_norm = os.path.normcase(os.path.normpath(lib))
        folder_norm = os.path.normcase(folder)
        if folder_norm == lib_norm:
            return "reject", (
                "不能把图库本身作为导入来源。\n"
                "图库内的图片会自动被识别为 managed，不需要导入。"
            )
        if folder_norm.startswith(lib_norm + os.sep):
            return "reject", (
                "不能导入图库内部的文件夹。\n"
                "图库内的图片会自动被识别为 managed，不需要导入。"
            )

    if is_system_dir(folder):
        return "warn", (
            f"这个路径看起来包含系统目录：\n{folder}\n\n"
            "导入它通常意义不大。确定要继续吗？"
        )

    return "ok", None


def ensure_library():
    lib = config.get_library_path()
    if lib and os.path.isdir(lib):
        database.set_library(lib)
        database.init_db()
        return True

    folder = QFileDialog.getExistingDirectory(
        None, "首次使用，请选择或新建一个文件夹作为总图库"
    )
    if not folder:
        return False

    config.set_library_path(folder)
    database.set_library(folder)
    database.init_db()
    return True


def main():
    init_image_readers()

    app = QApplication(sys.argv)

    config.cleanup_legacy_keys()

    if config.get_running_flag():
        config.set_safe_mode(True)

    config.set_running_flag(True)

    theme = config.get_theme()
    apply_theme(app, theme)

    if not ensure_library():
        config.set_running_flag(False)
        config.set_safe_mode(False)
        return

    try:
        database.fix_stale_running_batches()
    except Exception:
        pass

    w = MainWindow()
    w.show()

    rc = app.exec()

    config.set_running_flag(False)
    config.set_safe_mode(False)

    sys.exit(rc)


if __name__ == "__main__":
    main()