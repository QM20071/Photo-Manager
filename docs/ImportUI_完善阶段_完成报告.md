# Import UI 完善阶段 · 完成报告

**项目：** 个人图片管理器
**阶段：** Import UI 完善（Phase C 之后）
**日期：** 2026-09-19

---

## 一、背景

Phase C 完成后，实际使用中发现 Import 的痛点：

1. 导入时 UI 卡死（`import_folder` 在 UI 线程跑）
2. 没有进度反馈
3. 不能取消
4. 导入历史看不到
5. 不能"再次导入"同一个来源
6. 防呆不够强（盘符根目录可以强行继续）

---

## 二、范围

### 做

1. 后台线程导入（QThread）
2. 进度对话框（进度条 + 进度文字 + 取消按钮）
3. 协作式取消
4. 导入历史对话框
5. 再次导入（创建新 batch）
6. 盘符根目录直接拒绝
7. 移除来源（用户后续追加需求）

### 不做

- 增量导入 / 导入预览 / 整批撤销 / 断点续传 / 自动重试
- 多任务 / 哈希去重 / 导入队列 / 复杂线程池

---

## 三、设计冻结（v2.1）

### Import 三类结果
completed / cancelled / failed

### 统计定义

| 字段 | 定义 |
|---|---|
| `total_found` | 截止终止时，扫描阶段已实际发现的图片数量 |
| `new_count` | 实际已执行登记并成功新增的数量 |
| `skip_count` | 实际已执行登记并判断为已存在的数量 |

**不变量：`new_count + skip_count ≤ total_found`。**

### ImportBatch 生命周期
create → running
↓
try Import
↓
completed / cancelled / failed
↓
finally: finish_import_batch（统一出口）

**任何路径都不能留下 `running`。**

### 协作式取消

- 不杀线程
- 扫描阶段每 100 个文件检查一次（原 500，后优化）
- 登记阶段每 10 张图检查一次（原 50，后优化）
- `cancel_requested` 是简单 bool

### 防呆统一入口

`_validate_import_path` 检查顺序：

1. 必须存在且是目录
2. 盘符根目录 → 拒绝
3. 图库根目录 → 拒绝
4. 图库内部 → 拒绝
5. 系统目录 → 警告，可继续

---

## 四、代码改动

| 文件 | 操作 |
|---|---|
| `core/scanner.py` | 改 `import_folder` 签名和实现；新增 `CancelledError` |
| `core/import_worker.py` | 新建 |
| `ui/import_dialog.py` | 新建 |
| `ui/import_history_dialog.py` | 新建 |
| `main.py` | 改 `import_external_folder`；新增 `_validate_import_path` / `_run_import` / `open_import_history` / `closeEvent`；工具栏加"导入历史" |
| `database.py` | 新增 `get_source_stats` / `remove_source_completely` |

---

## 五、功能测试结果

| 测试 | 结果 | 说明 |
|---|---|---|
| A. 正常 Import | ✅ | 扫描 / 登记两阶段进度正常 |
| B. 重复 Import | ✅ | 全部跳过，不产生重复记录 |
| C. 扫描阶段取消 | ⏭️ 未直接验证 | 用户机器扫描速度较快，未能稳定触发。代码路径已实现 |
| D. 登记阶段取消 | ✅ | batch = cancelled，统计正确 |
| E. 最后一张取消边界 | ⏭️ 未直接验证 | 手动触发困难。代码逻辑已实现（`if (i+1) < total`）|
| F. ESC 关闭进度窗口 | ✅ | 无反应（符合设计）|
| G. 主窗口关闭时导入 | ✅ | 模态阻止，数据库 batch 正确（cancelled）|
| H. 重复启动 | ✅ | 模态阻止 |

### 测试中做的改进

**问题：** 检查点粒度太粗（扫描每 500 文件、登记每 50 张），取消响应慢。

**改进：** 改为扫描每 100 文件、登记每 10 张。

**效果：** 用户点取消后，对话框"瞬间"关闭（几百毫秒）。

### 真实场景测试

用户用 1000+ 张真实照片文件夹测试：

- 导入正常
- 取消响应良好
- batch 状态正确

---

## 六、新增功能：移除来源

### 需求

用户从 Phase C 完成后提出：旧扫描区允许"移除扫描区"，同时移除该区域登记的未整理图片。希望新模型也有对应功能。

### 实现

- `database.get_source_stats(source_id)`：查询 source 的 external 图片数 + batch 数
- `database.remove_source_completely(source_id)`：删除顺序 `images → batches → sources`
- `ImportHistoryDialog` 加"移除来源"按钮，带确认弹窗
- 移除后自动刷新"未整理"

### 关键约束

删除条件：

```sql
WHERE storage_type = 'external'
  AND file_path LIKE '<source_path>\%'