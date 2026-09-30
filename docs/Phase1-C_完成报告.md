# Phase 1 + Phase C 完成报告

**项目：** 个人图片管理器（Windows 离线工具）
**日期：** 2026-09-18
**阶段：** Phase 1 设计冻结 + Phase C 数据模型重构

---

## 一、Phase 1：设计冻结

### 背景

项目早期存在"扫描区"设计。用户曾将整个 D 盘（13 万文件）设为扫描区，
程序卡死，数据库被污染（从几百 KB 涨到 17MB），需手动清库恢复。

事故根本原因：

> "让用户任意指定一个目录作为扫描区"这个抽象本身就把不可控性引入了系统。

### 设计目标

把"扫描区"从长期核心机制，降级为一次性的"导入任务"。

### 冻结的 16 条核心决策

1. `images.id` 使用 SQLite 自增整数，作为永久 image_id，与路径无关
2. 路径只保留一个 `file_path` 字段，通过 `storage_type` 解释
3. 新增 `storage_type` / `organize_status` / `file_status`
4. `organize_status`（unsorted / sorted）与 `file_status`（available / missing / unreadable）独立
5. `album_rel_path` 暂时保留用于迁移兼容，迁移后不再权威
6. 数据库迁移严格分四阶段：A 加列 → B 迁移 → C 改代码 → D 清理
7. 迁移用独立 `migrate.py`
8. `config.json` 中旧 `scan_paths` 迁移到 `sources` 表
9. `sources` 是历史来源记录，启动时绝不自动递归扫描
10. Import 是一次性登记任务；Organize 才是实际移动到图库相册的操作
11. 相册继续使用图库内真实物理文件夹
12. 文件移动必须由 `FileManager` 统一处理；数据库更新在文件系统操作成功之后
13. 跨磁盘移动需要考虑临时文件、复制完成验证和异常中断
14. 外部图片可以通过 Organize 移入图库，`storage_type` 变成 `managed`
15. 图库内部路径使用相对路径，保证整个图库目录可以直接搬迁
16. 第一版不做：内容 Hash 去重、跟踪外部文件夹实时变化、自动恢复扫描任务、跟随符号链接

### 设计文档结构

- 第 1 节：核心概念定义（Library / Source / Import / Organize / Album / Image）
- 第 2 节：表设计（images / sources / import_batches，及保留表）
- 第 3 节：状态流转（organize_status × file_status 的组合语义 + 状态转移图）
- 第 4 节：文件移动流程（正常流程 + 异常处理 + SUCCESS/FAILED/PARTIAL）
- 第 5 节：迁移方案（新旧字段对照 + migrate.py 逻辑）

---

## 二、Phase C：数据模型重构

### 改造范围

| 文件 | 改动 |
|---|---|
| `database.py` | 新模型；`add_image` 返回 `(id, is_new)`；sources / import_batches / migration_state 表；`PRAGMA foreign_keys = ON` |
| `core/scanner.py` | 删除 `scan_all`；新增 `import_folder` / `check_library` / `scan_library_root_loose_files` / `scan_blacklist_folders` |
| `core/image_readers.py` | 新建；统一 HEIF 初始化 |
| `file_manager.py` | 三种结果 SUCCESS/FAILED/PARTIAL；同盘 rename，跨盘 temp+verify；`move_to_exact_path` 用于撤销 |
| `config.py` | 删除 scan_paths 依赖；新增 `cleanup_legacy_keys` |
| `main.py` | 启动不扫描；两个手动入口"扫描图库"和"导入文件夹"；进入相册自动扫描；所有 API 使用 image_id；撤销走 FileManager |
| `ui/dialogs.py` | 删除 `ScanPathDialog`；新增 `ImportFolderDialog`（占位） |

### 全项目旧模型搜索

搜索了：
- `scan_paths` / `scan_all` / `album_rel_path`
- `add_images(` / `move_image_record` / `delete_image_record`
- `shutil.move` / `os.rename` / `os.replace`
- `row["path"]` 等

结论：无关键残留。`undo_last` 的 `shutil.move` 已改为走 `FileManager.move_to_exact_path`。

---

## 三、功能测试结果

### 测试分组

| 组 | 内容 | 结果 |
|---|---|---|
| 1 | 启动 / 未整理 / 查看器 / 相册 / 收藏 / 排序 / EXIF / 刷新 | ✅ |
| 2 | Import（小文件夹导入、重复导入、图库边界拒绝） | ✅ |
| 3 | Organize（同盘移动，external→managed） | ✅ |
| 4 | Undo（撤销回原位，状态恢复） | ✅ |
| 5 | 删除（单张 + 相册） | ✅ |
| 6 | Check Library（missing / unreadable / available） | ✅ |
| 7 | 跨盘移动 | ⏭️ 未测 |

### 测试中发现并修复的问题

1. **`record_operation` 之前不生效**：旧版 `main.py` 的 `move_selected_to_album` 未调用新版 `move_files`。全量替换后修复。

2. **`undo_last` 报"数据库找不到记录"**：`operations.dst_path` 存绝对路径，而数据库 `managed` 记录的 `file_path` 是相对路径。修复：撤销时先用 `_compute_db_path` 转换成 `(storage_type, db_path)` 再查。

3. **撤销后图片回到根目录，"未整理"看不到**：`move_to_exact_path` 用旧记录覆盖了 `organize_status`。修复：改为根据新路径推导。

4. **5 条历史错乱记录**：状态与路径不一致，用一次性脚本修正。

---

## 四、EXE 打包测试

### 打包方式

- Nuitka 4.2.1
- standalone 模式（非 onefile）
- 命令：
python -m nuitka --standalone --enable-plugin=pyside6 ^
--include-package=core --include-package=ui --include-package=utils ^
--include-module=pillow_heif --output-dir=dist_nuitka main.py


### 测试环境

- 把 `main.dist` 复制到 `D:\_exe_test\main.dist`
- 手动放 `config.json`（指向 `D:/Resource/Picture`）
- 双击 `main.exe`

### 测试结果

| 项 | 结果 |
|---|---|
| exe 启动 | ✅ |
| UI 显示 | ✅ |
| 标题栏显示图库路径 | ✅ |
| "未整理" Tab | ✅ |
| 底部相册条 | ✅ 16 个 |
| 缩略图 | ✅ |
| PIL Corrupt EXIF warning | 与开发环境相同，可接受 |
| HEIC | ⏭️ 未测（无测试图片） |

---

## 五、Phase C 总体结论

> **Phase C 已完成并通过验收。**
>
> 已完成数据库、扫描器、文件管理器、主界面及相关调用方向新模型迁移，并完成项目级旧模型残留审计。
>
> 已通过启动、图库加载、Import、Organize、Undo、删除、相册、收藏、排序、EXIF、Check Library 等核心功能测试。
>
> 已完成 Nuitka standalone EXE 打包测试，并在独立测试目录中实际启动运行，基础功能正常。
>
> 当前没有发现阻塞 Phase C 收尾的代码或架构问题。
>
> **未覆盖测试项：**
>
> - 跨磁盘移动：因当前测试环境没有第二物理磁盘，未进行实际跨文件系统测试
> - HEIC/HEIF：因当前没有 HEIC 测试图片，未进行实际 EXE 环境验证
>
> 上述两项均记录为后续补充测试，不阻塞 Phase C 结束。

---

## 六、下一阶段

Phase C 结束后，进入 Phase 2。

Phase 2 的候选方向（尚未决定）：

- 可靠性继续增强
- UI / 操作体验
- Import / 历史记录
- Undo 体系
- 搜索与浏览效率
- 打包体积 / 启动速度

Phase 2 应优先从"实际使用体验"出发决定方向，而不是单纯"功能更多"。