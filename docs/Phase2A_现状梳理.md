# Phase 2A 前置：当前网格与缩略图链路梳理

- **日期：** 2026-09-20
- **目的：** 在写 Phase 2A 设计之前，先梳理当前实现的实际链路
- **方法：** 基于实际代码（`main.py` / `ui/delegate.py` / `core/thumbnails.py`）

---

## 一、网格（QListWidget）

### 当前实现

`main.py` 里：

```python
self.grid = QListWidget()
self.grid.setViewMode(QListWidget.IconMode)
self.grid.setIconSize(QSize(ICON_SIZE, ICON_SIZE))  # 160x160
self.grid.setResizeMode(QListWidget.Adjust)
self.grid.setSpacing(10)
self.grid.setMovement(QListWidget.Static)
self.grid.setSelectionMode(QListWidget.ExtendedSelection)
关键事实
用 QListWidget（不是 QListView + model）

用 IconMode 显示网格

每个图片是一个 QListWidgetItem

每个 QListWidgetItem 的 QIcon 里存一个 QPixmap（缩略图）

没有设置 setUniformItemSizes(True)

数据流动
数据库记录（list of dict）
    ↓
_populate_grid(rows)
    ↓
启动 ThumbnailLoader（QThread）
    ↓
ThumbnailLoader.batch_ready 信号
    ↓
_on_batch_with_rows(batch)
    ↓
_add_grid_item_from_row(row, pixmap)
    ↓
QListWidgetItem + QIcon(pixmap)
    ↓
self.grid.addItem(item)
已识别的问题
问题 1：所有 QListWidgetItem 常驻内存

每张图的缩略图 QPixmap（160×160 RGBA ≈ 100KB）都挂在 QIcon 上

1000 张 ≈ 100MB；10000 张 ≈ 1GB

切换 Tab / 相册时，self.grid.clear() 会释放旧的，但新的又创建

本质：内存占用与图片总数线性相关

问题 2：没有虚拟化

QListWidget 自己会做有限的视图虚拟化（不可见的 item 不绘制）

但 item 对象本身和 QIcon 都常驻内存

所以"视图虚拟化" ≠ "内存虚拟化"

问题 3：_populate_grid 会停止上一个 loader，但

如果用户快速切换相册，可能反复停 / 启线程

每次重启都要重新扫描整个列表

二、缩略图加载（ThumbnailLoader）
当前实现
core/thumbnails.py：

python
class ThumbnailLoader(QThread):
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
关键事实
一次性遍历整个 images 列表

每 20 张发一批 batch_ready

主线程收到批次后逐项 addItem

已识别的问题
问题 1：QPixmap 在 worker 线程里创建

Qt 文档明确说：QPixmap 应该在 GUI 线程使用

在非 GUI 线程里创建 QPixmap，在某些平台上是未定义行为

应该用 QImage 在 worker 线程里解码，然后通过信号传给主线程，主线程再转 QPixmap

问题 2：worker 不区分"可见"和"不可见"

它不管用户当前滚到哪里

一律按列表顺序生成

用户滚到第 500 张时，前 499 张已经生成完了（浪费）

问题 3：没有内存缓存，只有磁盘缓存

每次都要 QPixmap(cache_file) 重新读磁盘

即使刚刚看过，也可能被换出

应该加内存 LRU

问题 4：缓存是 PNG

PNG 无损，文件大，解码慢

缩略图不需要无损，可以改 JPEG / WebP

问题 5：大图解码路径

make_thumbnail 里的 Image.open + convert + thumbnail + save

对 8K 图片，Image.open 就是完整解码

应该用 Image.draft() 或缩略图专用接口，避免完整解码

make_thumbnail 的实现
python
def make_thumbnail(image_path, size=160):
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
关键问题
Image.open 本身是懒加载，但 convert("RGB") 会触发完整解码

8K JPEG → 完整解码 → 内存里 7680×4320×3 ≈ 95MB → 再缩到 160px

解码 8K 图是 CPU 密集操作

多张并发解码会跑满所有核 → 风扇狂转

三、缩略图缓存（磁盘）
当前实现
python
def cache_path_for(image_path):
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
关键事实
按 path + mtime + size 算 MD5

缓存文件是 <MD5>.png

存在 library/cache/

已识别的问题
问题 1：缓存文件用 PNG

文件大，I/O 慢

解码 PNG 比 JPEG 慢

问题 2：缓存目录没有 LRU 清理

生成的缓存文件永远不删

图库变大后，缓存目录会无限增长

问题 3：缓存命中判断是同步的

os.path.exists(cache_file) 是同步 I/O

在 UI 线程里调用（如 PreviewArea.show_image）会阻塞 UI

四、Delegate
当前实现
ui/delegate.py：

python
class ThumbnailDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        painter.save()

        icon = index.data(Qt.DecorationRole)
        full_name = index.data(Qt.UserRole + 1)
        selected = bool(option.state & QStyle.State_Selected)

        rect = option.rect

        # 背景
        if selected:
            painter.fillRect(rect, get_color("selected_bg"))
        else:
            painter.fillRect(rect, get_color("window_bg"))

        # 缩略图
        if icon is not None and isinstance(icon, QIcon):
            pm = icon.pixmap(ICON_SIZE, ICON_SIZE)
            if not pm.isNull():
                icon_x = rect.x() + (rect.width() - pm.width()) // 2
                icon_y = rect.y() + 8
                painter.drawPixmap(icon_x, icon_y, pm)

        # 文件名
        ...

        painter.restore()
关键事实
index.data(Qt.DecorationRole) 取 QIcon

icon.pixmap(ICON_SIZE, ICON_SIZE) 每次都调用

painter.drawPixmap 绘制

已识别的问题
问题 1：QIcon 里存的是已缩放的 pixmap

QIcon 每次 pixmap(w, h) 调用会做缩放

但实际上缩略图已经是 160×160，不需要再缩放

这个调用可能反而增加开销

问题 2：文件名用 QFontMetrics.elidedText 每次计算

每次都重新算省略

应该缓存

问题 3：没有 hover 状态

option.state 里其实有 State_MouseOver，但没用

五、主窗口的缩略图缓存
PreviewArea.show_image
python
def show_image(self, path):
    pixmap = None
    try:
        cache_file = cache_path_for(path)
        if os.path.exists(cache_file):
            pixmap = QPixmap(cache_file)
            if pixmap.isNull():
                pixmap = None
    except Exception:
        pixmap = None

    if pixmap is None:
        pixmap = QPixmap(path)
    ...
关键问题
在 UI 线程里同步读磁盘缓存

如果缓存不存在，QPixmap(path) 直接加载原图

8K 图会卡 UI 线程

六、已识别的核心问题清单
#	问题	影响	建议方向
1	所有缩略图常驻 QListWidgetItem	内存与图片数线性增长	换 QListView + model
2	ThumbnailLoader 一次性处理全部	首次加载慢，不区分可见性	改成可见区域驱动
3	QPixmap 在 worker 线程创建	可能线程不安全	改用 QImage 传递
4	没有内存 LRU 缓存	反复读磁盘	加 LRU
5	缓存是 PNG	文件大、解码慢	改 JPEG / WebP
6	8K 图完整解码	CPU 密集，风扇狂转	用 draft() 或专用接口
7	缓存目录无清理	无限增长	加 LRU 清理
8	PreviewArea 在 UI 线程读盘	卡 UI	移到后台线程
9	Delegate 每次做 elidedText	小开销	缓存
10	QIcon.pixmap() 重复缩放	无谓开销	直接存 QPixmap
七、需要审核方确认的方向
问题 1：QListView + QAbstractListModel 是否是正确路线？
还是应该保留 QListWidget，但用其他方式优化？

审核方原话：推荐 QListView + QAbstractListModel + Delegate

问题 2：ThumbnailManager 的接口设计
应该是 request(image_id) → 异步回调？

还是 request_batch(image_ids) → 批量回调？

还是 request_range(start, end) → 按可见范围？

问题 3：内存 LRU 的容量
审核方说"不要现在冻结"

那应该在哪个阶段决定？基于什么测试？

问题 4：8K 解码的优化方式
Pillow 的 Image.draft() 可以在 JPEG 解码时降低分辨率

但只对 JPEG 有效，PNG / WebP / HEIC 不一定支持

是否需要针对不同格式分别优化？

问题 5：缓存格式
PNG → JPEG 质量 85？

还是 WebP？

WebP 体积更小但兼容性略差（Qt 支持吗？）

问题 6：QPixmap 线程安全
审核方是否同意"worker 线程应该用 QImage"？

还是 Qt 6 的 QPixmap 在 worker 线程里其实可以？

问题 7：B 和 F 的接口边界
B（性能）改完后，F（UI）会不会需要再改 B？

比如圆角、间距改了，delegate 的绘制逻辑要变

是否应该先把 B 的架构稳定，再改 F 的视觉细节？

八、下一步
审核方确认上述问题的方向

审核方给出 Phase 2A 设计的建议范围

DeepSeek 写 Phase 2A 设计 v1

审核方审核 v1

开始改代码

（梳理完成，等待审核方意见。）