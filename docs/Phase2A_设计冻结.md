# Phase 2A 设计：可见区域驱动的缩略图浏览架构

- **日期：** 2026-09-20
- **状态：** 冻结（v6 封版）
- **前置：** `Phase2A_前置_现状梳理.md`
- **范围：** 仅 Phase 2A（性能重构），不含 Phase 2B（UI 视觉改版）

---

## 目录

1. 目标与范围
2. 新旧架构对照
3. 核心概念
4. ImageListModel
5. ThumbnailManager
6. DecodeWorker
7. Memory LRU
8. Disk Cache
9. Visible / Prefetch 计算
10. Request Token 与 Generation
11. 完整生命周期规则
12. 结果验证（三重检查）
13. Priority Promotion 行为契约
14. 4K/8K 各格式解码优化
15. Preview 管线
16. FAILED 状态与重新尝试
17. 涉及文件的改动
18. 明确不做
19. 实现步骤

---

## 一、目标与范围

### 目标

把当前"一次性加载整个相册缩略图"的架构，改成"可见区域驱动"的架构。

解决：

- 图库增大后内存线性增长
- 首次进入相册慢
- 滚动卡顿
- 大图解码时风扇狂转

### 范围

**做：**

- `QListWidget` → `QListView` + `QAbstractListModel`
- `ThumbnailLoader` → `ThumbnailManager` + `DecodeWorker`
- 可见区域驱动加载
- Memory LRU
- 按格式优化解码路径
- Preview 最小改动（不阻塞 UI）

**不做：**

- 缓存格式改版（PNG → JPEG / WebP）
- LRU 具体容量
- 全图库预生成缩略图
- 分页
- 多线程线程池
- GPU 自定义渲染
- UI 动画
- 圆角视觉改版（Phase 2B）
- 图标体系重做（Phase 2B）
- elidedText 缓存（Phase 2B）
- hover 状态（Phase 2B）
- 磁盘缓存自动清理（预留接口）
- Preview 完整重构

---

## 二、新旧架构对照

### 旧架构
数据库记录
↓
ThumbnailLoader（QThread）
↓
遍历全部图片，每 20 张 batch_ready
↓
QListWidgetItem + QIcon(QPixmap)
↓
QListWidget

text

**问题：**

- 所有缩略图常驻 QListWidgetItem
- ThumbnailLoader 不区分可见性
- QPixmap 在 worker 线程创建
- 无内存缓存
- 无优先级

### 新架构
数据库记录
↓
ImageListModel（只存元数据）
↓
QListView
↓
View 检测可见区域
↓
ThumbnailManager.request_many(ids, priority)
↓
┌──────────────────────────────────────┐
│ GUI 线程： │
│ 检查 Memory LRU │
│ ├─ 命中 → 立即返回 QPixmap │
│ └─ 未命中 → 从 Model 取 file_path │
│ 派发给 Worker │
└──────────────────────────────────────┘
↓
DecodeWorker（1 个线程）
↓
┌──────────────────────────────────────┐
│ Worker 线程： │
│ 检查 generation │
│ ├─ 过期 → 跳过 │
│ └─ 有效： │
│ 检查 Disk Cache │
│ ├─ 命中 → 读缓存 → QImage │
│ └─ 未命中 → Pillow 解码 → QImage│
└──────────────────────────────────────┘
↓
emit thumbnail_ready(image_id, QImage, generation, token)
↓
┌──────────────────────────────────────┐
│ GUI 线程： │
│ 三重检查（见第十二节） │
│ ├─ 过期 → 丢弃 │
│ └─ 有效： │
│ QImage → QPixmap │
│ 存入 Memory LRU │
│ 更新 _states │
│ Model.dataChanged(image_id) │
└──────────────────────────────────────┘
↓
Delegate 重绘该项

text

---

## 三、核心概念

### 三个职责

| 组件 | 职责 |
|---|---|
| **ImageListModel** | "这是什么图片？" |
| **ThumbnailManager** | "这张图现在有没有缩略图？" |
| **Delegate** | "怎么画？" |

### 两个有效性维度
generation
↓
控制"页面 / Model 上下文是否已经换了"

request_token
↓
控制"同一 image_id 的这个具体请求是否仍然有效"

text

**两者负责两个不同层级的问题。缺一不可。**

### 线程边界
Worker 线程：
Pillow 解码
磁盘缓存读写
生成 QImage

GUI 线程：
查 Memory LRU
QImage → QPixmap
更新 Model / View

text

---

## 四、ImageListModel

### 字段

```python
class ImageItem:
    image_id: int
    file_path: str      # 绝对路径
    filename: str
    favorite: bool
接口
python
class ImageListModel(QAbstractListModel):
    def __init__(self):
        super().__init__()
        self._items: list[ImageItem] = []
        self._id_to_index: dict[int, int] = {}

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._items)

    def data(self, index, role) -> Any:
        if not index.isValid():
            return None
        item = self._items[index.row()]
        if role == Qt.DisplayRole:
            return item.filename
        if role == Qt.UserRole:
            return item.image_id
        if role == Qt.UserRole + 1:
            return ("⭐ " if item.favorite else "") + item.filename
        if role == Qt.UserRole + 2:
            return item.favorite
        return None

    def set_images(self, items: list[ImageItem]):
        self.beginResetModel()
        self._items = items
        self._id_to_index = {item.image_id: i for i, item in enumerate(items)}
        self.endResetModel()

    def get_file_path(self, image_id: int) -> str | None:
        idx = self._id_to_index.get(image_id)
        if idx is None:
            return None
        return self._items[idx].file_path

    def notify_thumbnail_ready(self, image_id: int):
        idx = self._id_to_index.get(image_id)
        if idx is None:
            return
        model_index = self.index(idx, 0)
        self.dataChanged.emit(model_index, model_index)

    def invalidate_thumbnail(self, image_id: int):
        self.notify_thumbnail_ready(image_id)

    def clear(self):
        self.beginResetModel()
        self._items = []
        self._id_to_index = {}
        self.endResetModel()
关键
Model 不返回 QPixmap

Model 不持有 QPixmap

Model 提供 get_file_path 供 ThumbnailManager 查询

五、ThumbnailManager
接口
python
class ThumbnailManager(QObject):
    thumbnail_ready = Signal(int, QPixmap)

    def __init__(self, model: ImageListModel, worker: DecodeWorker):
        self._model = model
        self._worker = worker
        self._states: dict[int, RequestState] = {}
        self._memory_cache = MemoryThumbnailCache(max_bytes=...)
        self._generation: int = 0
        self._request_tokens: dict[int, int] = {}

        self._worker.thumbnail_generated.connect(self._on_thumbnail_generated)
        self._worker.decode_failed.connect(self._on_decode_failed)

    def _current_token(self, image_id: int) -> int:
        token = self._request_tokens.get(image_id, 0)
        if token == 0:
            token = 1
            self._request_tokens[image_id] = token
        return token

    def request(self, image_id: int, priority: int) -> None:
        ...

    def request_many(self, image_ids: list[int], priority: int) -> None:
        for image_id in image_ids:
            self.request(image_id, priority)

    def get_cached(self, image_id: int) -> QPixmap | None:
        return self._memory_cache.get(image_id)

    def invalidate(self, image_id: int) -> None:
        old_token = self._request_tokens.get(image_id, 0)
        self._request_tokens[image_id] = old_token + 1
        self._states.pop(image_id, None)
        self._memory_cache.pop(image_id, None)

    def bump_generation(self) -> int:
        self._generation += 1
        self._worker.set_generation(self._generation)
        self._states = {
            k: v for k, v in self._states.items()
            if v.generation == self._generation
        }
        return self._generation

    def current_generation(self) -> int:
        return self._generation
状态定义
python
class ThumbState:
    UNKNOWN  = 0
    QUEUED   = 1
    LOADING  = 2
    LOADED   = 3
    FAILED   = 4

class RequestState:
    def __init__(self, state, generation, priority=None, token=None):
        self.state = state
        self.generation = generation
        self.priority = priority
        self.token = token
优先级常量
python
PRIORITY_VISIBLE    = 0
PRIORITY_PREFETCH   = 1
PRIORITY_BACKGROUND = 2
六、DecodeWorker
接口
python
class DecodeWorker(QThread):
    thumbnail_generated = Signal(int, QImage, int, int)   # (image_id, qimage, gen, token)
    decode_failed = Signal(int, str, int, int)             # (image_id, error, gen, token)

    def __init__(self):
        super().__init__()
        self._queue = queue.PriorityQueue()
        self._stop = False
        self._current_generation = 0

    def enqueue(self, image_id, file_path, priority, generation, token):
        self._queue.put((priority, image_id, file_path, generation, token))

    def reprioritize(self, image_id, new_priority):
        # 行为契约见第十三节
        # 具体实现由代码阶段决定
        ...

    def set_generation(self, gen):
        self._current_generation = gen

    def run(self):
        while not self._stop:
            try:
                priority, image_id, file_path, gen, token = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue

            if gen != self._current_generation:
                continue

            try:
                qimage = self._decode_or_load_cache(image_id, file_path)
                if gen != self._current_generation:
                    continue
                self.thumbnail_generated.emit(image_id, qimage, gen, token)
            except Exception as e:
                self.decode_failed.emit(image_id, str(e), gen, token)

    def _decode_or_load_cache(self, image_id, file_path) -> QImage:
        cache_file = cache_path_for(file_path)
        if os.path.exists(cache_file):
            qimage = QImage(cache_file)
            if not qimage.isNull():
                return qimage
        qimage = decode_image(file_path, target_size=160)
        qimage.save(cache_file, "PNG")
        return qimage

    def stop(self):
        self._stop = True
单 Worker
Phase 2A 第一版固定 1 个 Worker。

根据 benchmark 决定是否增加到 2 个。不追求理论吞吐量。

七、Memory LRU
接口
python
class MemoryThumbnailCache:
    def __init__(self, max_bytes):
        self.max_bytes = max_bytes
        self._cache = OrderedDict()
        self._current_bytes = 0

    def get(self, image_id) -> QPixmap | None:
        if image_id in self._cache:
            self._cache.move_to_end(image_id)
            return self._cache[image_id]
        return None

    def put(self, image_id, pixmap: QPixmap):
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

    def _estimate_size(self, pixmap) -> int:
        return pixmap.width() * pixmap.height() * 4

    def _evict_if_needed(self):
        while self._current_bytes > self.max_bytes and self._cache:
            _, evicted = self._cache.popitem(last=False)
            self._current_bytes -= self._estimate_size(evicted)
待测参数
只冻结"有上限"，不冻结具体 max_bytes。

测试场景： 951 / 5000 / 10000 张图库。

观察： 空闲内存、进入相册后内存、连续滚动后内存、快速滚动后内存、CPU、缓存命中率、UI 帧率。

根据结果决定 max_bytes。

明确：max_bytes 是缓存预算，不是 Qt 实际内存占用的精确测量。

八、Disk Cache
保持 PNG
理由：

PNG 无损、兼容透明通道

改格式需要 benchmark 支持

不是当前性能瓶颈

Cache Version
python
THUMBNAIL_CACHE_VERSION = 1

def cache_path_for(image_path):
    ...
    h = hashlib.md5(key.encode("utf-8")).hexdigest()
    return os.path.join(
        library_cache_dir(),
        f"v{THUMBNAIL_CACHE_VERSION}_{h}.png"
    )
THUMBNAIL_CACHE_VERSION 定义为"缩略图算法版本"。

以下变化都应该自增 version：

文件格式（PNG → JPEG）

尺寸（160 → 192）

背景填充方式

EXIF orientation 处理

缩放算法

颜色空间

JPEG / WebP 参数

读写都在 Worker 线程
GUI 线程不做任何磁盘 I/O。

磁盘缓存清理
Phase 2A 不实现。 只预留接口。

九、Visible / Prefetch 计算
触发时机
View 监听：

scrollContentsBy —— 滚动

resizeEvent —— 窗口大小变化

modelReset —— 模型重置

计算方式
不能简单假设 indexAt(topLeft) 和 indexAt(bottomRight) 覆盖所有可见项。

对于 IconMode（网格模式）：

两个 index 只作为参考

必须确保所有可见 item 的 row 都被覆盖

不得漏掉可见项

原则：

compute_visible_range() 必须返回 viewport 中实际可见的全部 model row。不要求严格只包含可见项，但不得漏掉可见项。

宁可多请求几个 prefetch，也不能漏掉当前屏幕里的图片。

prefetch 范围
可见范围前后各 N 项。N 待测。

请求触发
Visible 请求：

立即触发（不防抖）

滚动时每次都触发

ThumbnailManager 的请求去重会处理重复

Prefetch 请求：

用 QTimer 防抖（50-100ms）

滚动停止后才触发

十、Request Token 与 Generation
职责
text
generation
    ↓
控制"页面 / Model 上下文是否已经换了"

request_token
    ↓
控制"同一 image_id 的这个具体请求是否仍然有效"
Token 生命周期 5 条约束
约束 1：invalidate(image_id) 必须递增 token

约束 2：创建新的请求生命周期时，必须记录该请求当前的 token

约束 3：普通重复请求不得递增 token

约束 4：generation 切换本身不必递增 token，但新请求必须记录新的 generation

约束 5：结果必须同时匹配 generation + request_token + 当前有效请求状态

十一、完整生命周期规则
text
QUEUED / LOADING
→ 普通 request：复用 token
→ 优先级更高：更新优先级，不递增 token

LOADED
→ 缓存存在：直接返回
→ LRU 淘汰：使用当前请求生命周期重新排队（复用 token）

FAILED
→ 用户再次 request：创建新的请求生命周期
→ token 自增
→ QUEUED
→ 重新解码

invalidate
→ token 自增
→ 清理 state / cache
request() 完整逻辑
python
def request(self, image_id: int, priority: int) -> None:
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
        if priority < state_info.priority:
            state_info.priority = priority
            self._worker.reprioritize(image_id, priority)
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
十二、结果验证（三重检查）
_on_thumbnail_generated
python
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
_on_decode_failed
同 _on_thumbnail_generated 的三重检查。

python
def _on_decode_failed(self, image_id, error, gen, token):
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
十三、Priority Promotion 行为契约
不冻结数据结构
具体 PriorityQueue 实现方式（删除旧项、lazy invalidation、priority dict 等）由代码阶段决定。

冻结行为契约
同一 image_id 同时存在任务时：

不产生两个最终有效任务

VISIBLE 优先于 PREFETCH

旧低优先级任务最终不会重复生成两份结果

generation 过期任务可以直接丢弃

推荐实现
懒失效 + 旧条目跳过：

队列里保留旧条目，标记失效

取出时检查，失效则跳过

新条目正常入队

十四、4K/8K 各格式解码优化
目标
不为了 160×160 缩略图，无意义地构造完整 8K RGB 图。

按格式实验
JPEG
候选方案：

Image.draft(mode, size) —— 在 JPEG 解码时降采样

Image.thumbnail(size, Image.LANCZOS) —— 当前用的

测试： 8K JPEG → 160px，用 draft() vs 不用。对比解码时间、内存峰值、CPU。

PNG
当前暂不采用 draft() 路径，先以实测结果决定是否需要其他优化。

不预设"PNG 通常不严重"。

WebP
建立 benchmark 样本并测试当前 Pillow 解码路径。

HEIC
建立 benchmark 样本并测试当前 pillow-heif 解码路径。

BMP
建立 benchmark 样本并测试。

实验步骤
对每种格式：

准备样本（8K / 4K / 1K）

测 Image.open + convert + thumbnail 的耗时

测优化方案（如果有）

对比

根据结果决定具体优化方案。不在设计阶段冻结。

十五、Preview 管线
Phase 2A 范围
只做 Thumbnail 完整重构。

Preview 只做最小改动：

不在 GUI 线程同步加载 8K 原图

原图/缓存 → 后台线程 → QImage

GUI 线程：QImage → QPixmap

共享解码入口
架构上必须存在一个共享的底层解码入口。

文件位置可选（core/image_decode.py 或 core/thumbnails.py），但架构职责不可选。

否则代码阶段会出现 Thumbnail 和 Preview 各自写一套 Pillow 解码。

十六、FAILED 状态与重新尝试
规则
text
FAILED
→ 用户再次 request
→ token 自增
→ QUEUED
→ 重新解码
解除 FAILED 的其他方式
invalidate(image_id) —— 单项失效

refresh / check_library —— 批量失效

切换相册 / 刷新 Tab —— 通过 generation 自然失效

占位符
Phase 2A 冻结：失败项必须有稳定的非空白占位状态。

具体视觉样式（问号 / broken image 图标 / "无法生成缩略图"）属于 Phase 2B。

十七、涉及文件的改动
文件	操作
core/thumbnails.py	重构为 ThumbnailManager + DecodeWorker + MemoryThumbnailCache
core/image_decode.py	新建（架构职责必须）：共享解码入口
ui/image_list_model.py	新建：ImageListModel
ui/delegate.py	改造：适配 Model/View
main.py	改网格部分：QListWidget → QListView
viewer.py	改 Preview：8K 原图不在 UI 线程加载
database.py	不改
十八、明确不做
缓存格式改版（PNG → JPEG / WebP）

LRU 具体容量

全图库预生成缩略图

分页

多线程线程池

GPU 自定义渲染

UI 动画

圆角视觉改版（Phase 2B）

图标体系重做（Phase 2B）

elidedText 缓存（Phase 2B）

hover 状态（Phase 2B）

磁盘缓存自动清理（预留接口）

Preview 完整重构（只做"不阻塞 UI"的最小改动）

十九、实现步骤
步骤	内容	依赖
1	ImageListModel（不含缩略图）	无
2	QListView 替换 QListWidget（最小可运行）	步骤 1
3	DecodeWorker（单线程，无 generation/token）	无
4	ThumbnailManager（含 generation/token/LRU）	步骤 1、3
5	接入 View：可见范围计算 + request	步骤 2、4
6	Delegate 改造（从 ThumbnailManager 取图）	步骤 5
7	Preview 异步化（最小改动）	无
8	cache version 加入	无
9	测试：951 / 5000 / 10000	全部
每一步都可以单独测试。