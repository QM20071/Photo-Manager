# Phase 2A 完成报告

- **日期：** 2026-09-23
- **阶段：** Phase 2A（浏览性能与网格架构重构）
- **配套设计：** `Phase2A_设计_最终版.md`
- **状态：** 完成

---

## 一、阶段目标

把"一次性加载整个相册缩略图"的旧架构，改成"可见区域驱动"的新架构。

解决：

- 图库增大后内存线性增长
- 首次进入相册慢
- 滚动卡顿
- 大图解码时风扇狂转

---

## 二、设计冻结

**设计文档：** `Phase2A_设计_最终版.md`

核心概念：

- **ImageListModel**：只存元数据，不存 QPixmap
- **ThumbnailManager**：管理缩略图请求 / 缓存 / 生命周期
- **DecodeWorker**：后台解码线程
- **Memory LRU**：有限容量的内存缩略图缓存
- **generation**：页面 / Model 上下文级有效性
- **request_token**：单个 image_id 请求级有效性
- **可见区域驱动**：只请求屏幕内 + 前后若干项

---

## 三、实现内容

### 新建文件

| 文件 | 作用 |
|---|---|
| `ui/image_list_model.py` | `ImageListModel` + `ImageItem` |
| `core/decode_worker.py` | `DecodeWorker` + `decode_image` + `cache_path_for` |
| `core/thumbnail_manager.py` | `ThumbnailManager` + `MemoryThumbnailCache` + `RequestState` |
| `core/preview_worker.py` | `PreviewWorker` + `load_preview_qimage` |

### 修改文件

| 文件 | 改动 |
|---|---|
| `ui/delegate.py` | 从 `ThumbnailManager.get_cached()` 取缩略图，不再依赖 `DecorationRole` |
| `main.py` | `QListWidget` → `QListView` + Model；可见范围计算；启动无响应优化 |

### 不改文件

- `database.py`
- `config.py`
- `file_manager.py`
- `viewer.py`（查看器暂时保持同步加载）
- `core/thumbnails.py`（旧的 `ThumbnailLoader` 保留，暂未清理）

---

## 四、关键决策

### 1. `QListWidget` → `QListView` + `QAbstractListModel`

**理由：** `QListWidgetItem` 把数据和视图绑定，无法按需加载缩略图。

### 2. Model 不持有 QPixmap

**理由：** 内存与图片总数线性相关的问题。

**实现：**

- Model 只存 `image_id` / `file_path` / `filename` / `favorite`
- Delegate 通过 `ThumbnailManager.get_cached(image_id)` 取缩略图

### 3. 可见区域驱动

**理由：** 只请求屏幕内 + 前后若干项。

**实现：**

- 滚动 / resize 时重新计算可见范围
- 50ms 防抖（滚动停止后才请求）
- `_compute_visible_rows` 用 `indexAt` + 滚动条估算

**重要发现：** `QListView.indexAt()` 在 IconMode 下不稳定（返回无效 index）。最终方案：`indexAt` 失败时用"滚动条位置 / 行高"估算。

### 4. 单 Worker

**理由：** 用户明确要求"风扇不狂转"。多线程会跑满 CPU。

**实现：** 固定 1 个 `DecodeWorker` 线程。

### 5. generation + request_token

**理由：** 防止旧请求污染新页面 / 新请求。

**实现：**

- `generation`：切换 Tab / 相册时递增
- `request_token`：`invalidate` / `FAILED` 后重新请求时递增
- 结果必须同时匹配 generation + token + 当前状态

### 6. JPEG `draft()`

**理由：** 避免 8K JPEG 完整解码。

**实现：** `decode_image` 里对 JPEG 调 `img.draft("RGB", (max_side * 2, max_side * 2))`。

**限制：** PNG / WebP / HEIC 不支持 draft，走完整解码。

### 7. 启动无响应优化

**问题：** 10520 条记录时，`_load_rows` 主线程阻塞。

**方案 A + 分批创建（不用真异步）：**

- `_load_rows` 各阶段间 `QApplication.processEvents()`
- `_populate_grid` 每 1000 条 `processEvents()`
- `load_unsorted` / `load_favorites` / `enter_album` 在查数据库前 `processEvents`

**效果：**

- UI 大部分时间可交互
- 用户能看到进度（"正在创建列表 1000 / 10520..."）
- 只有两个短暂真正阻塞点（读数据库、`set_images`）

---

## 五、测试结果

### 小规模（969 张）

- 首次进入：几乎瞬间
- 滚动：流畅
- 缩略图：按需加载
- 相册封面：正常

### 大规模（10520 张）

| 项 | 结果 |
|---|---|
| 首次进入 | 短暂无响应 2 次（读数据库 + `set_images`），中间 UI 可交互 |
| 第二次进入 | 秒进（SQLite 缓存） |
| 滚动 | 流畅 |
| 缩略图 | 只对可见范围加载 |
| 缺失文件（测试记录） | 显示占位符 |
| 内存 | 正常 |
| CPU / 风扇 | 空闲时接近 0% |

### 4K / 8K 图片

- 4K+ PNG 共 25 张
- 首次解码 < 1 秒
- 第二次瞬间（缓存）

### Preview 异步化

- 单击 8K 图不再卡 UI
- 快速点击多张图，最终显示最后点击的那张

---

## 六、未完成 / 已知问题

### 未完成

- **Delegate 优化**（`elidedText` 缓存）：跳过，收益小
- **旧 `ThumbnailLoader` 清理**：保留，暂未使用
- **查看器（`viewer.py`）异步化**：保持同步加载，未改

### 已知问题

- **启动时两次短暂无响应**：读数据库 + `set_images` 阶段，方案 A 无法消除，需真异步（C2，未做）
- **`QListView.indexAt()` 在 IconMode 下不稳定**：已用"滚动条估算"绕过
- **`scan_all` / `ThumbnailLoader` 等旧代码仍存在**：未清理

---

## 七、遗留的技术债

| 项 | 说明 |
|---|---|
| 旧 `ThumbnailLoader` | `core/thumbnails.py` 里保留，未使用 |
| 旧 `cache_path_for` | `core/thumbnails.py` 和 `core/decode_worker.py` 各有一份 |
| `viewer.py` 同步加载 | 双击打开的查看器仍同步加载 8K 原图 |
| `-1` 负数 image_id 表示相册 | 临时方案，不优雅 |
| `_compute_visible_rows` 的估算 | 不精确，但"宁可多请求" |

**这些不影响功能，留待未来处理。**

---

## 八、性能数据

### 969 张图库

- 首次进入"未整理"：< 1 秒
- 缩略图加载：瞬间
- 滚动：流畅

### 10520 张图库（测试）

- 首次进入：2-3 秒（含 2 次短暂无响应）
- 第二次进入：< 1 秒
- 滚动：流畅
- 内存：~50-100MB

### 4K+ PNG

- 25 张
- 首次解码 < 1 秒

---

## 九、结论

> **Phase 2A 完成。**
>
> 已完成从"一次性加载整个相册缩略图"到"可见区域驱动"的架构重构。
>
> 已通过 969 张和 10520 张两个规模的测试。
>
> 已通过 4K / 8K 图片的加载测试。
>
> 已通过 Preview 异步化测试。
>
> 已知的"启动时两次短暂无响应"是方案 A 的局限，不影响日常使用，如需彻底解决需要真异步（未做）。

---

## 十、下一阶段

**Phase 2B：UI 视觉改版**

目标：

- 现代桌面工具风格（Eagle / Notion / Figma 风格）
- 颜色、圆角、间距、字体、图标
- 悬停 / 选中反馈

**Phase 2B 需要独立设计文档。**