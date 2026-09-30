# Import UI 完善阶段 · 设计 v2.1（冻结）

- **日期：** 2026-09-19
- **状态：** 冻结
- **配套文档：** `ImportUI_完善阶段_完成报告.md`

---

## 目录

1. 范围
2. Import 三类结果
3. 统计定义
4. ImportBatch 生命周期
5. 协作式取消
6. CancelledError
7. 进度信号
8. add_image 异常处理
9. finish_import_batch 失败处理
10. 防呆统一入口
11. 线程生命周期
12. 移除来源
13. 本阶段明确不做
14. 未覆盖测试项

---

## 1. 范围

### 做

1. 后台线程导入（QThread）
2. 进度对话框（进度条 + 进度文字 + 取消按钮）
3. 协作式取消
4. 导入历史对话框
5. 再次导入（创建新 batch）
6. 盘符根目录直接拒绝
7. 移除来源（追加需求）

### 不做

- 增量导入
- 导入预览
- 整批撤销
- 断点续传
- 自动重试
- 多任务
- 哈希去重
- 导入队列
- 复杂线程池

---

## 2. Import 三类结果
Import
│
┌─────────┼─────────┐
│ │ │
正常完成 用户取消 异常
│ │ │
completed cancelled failed

text

---

## 3. 统计定义

| 字段 | 定义 |
|---|---|
| `total_found` | 截止终止时，扫描阶段已实际发现的图片数量 |
| `new_count` | 实际已执行登记并成功新增的数量 |
| `skip_count` | 实际已执行登记并判断为已存在的数量 |

**不变量：** `new_count + skip_count ≤ total_found`

**未登记的图片：** 既不算 new，也不算 skip

### 场景示例

**扫描阶段取消**
已扫描 3000 个文件
已发现 183 张图片
用户取消

→ total_found = 183
→ new_count = 0
→ skip_count = 0
→ status = cancelled

text

**登记阶段取消**
已发现 240 张
已登记 200 张（新增 180，跳过 20）
用户取消

→ total_found = 240
→ new_count = 180
→ skip_count = 20
→ status = cancelled
→ 剩余 40 张：不计算

text

---

## 4. ImportBatch 生命周期
create_import_batch
↓
status = running
↓
try: Import
↓
┌───────┼──────────┐
完成 取消 异常
↓ ↓ ↓
done cancelled failed
↓
finish_import_batch
（统一出口，finally）

text

**关键原则：** 任何路径都不能留下 `running`

**实现结构：**

- `try` — 主流程
- `except CancelledError` — 用户取消
- `except Exception` — 异常失败
- `finally` — 统一收尾

---

## 5. 协作式取消

### 原则

不杀线程，让 worker 自己结束。

### 流程
用户点取消
↓
ImportWorker.cancel()
↓
cancel_requested = True
↓
worker 在安全检查点发现
↓
raise CancelledError
↓
顶层捕获 → status = "cancelled"
↓
finally: finish_import_batch(cancelled)
↓
emit finished_import(result)
↓
UI 关闭

text

### 安全检查点

| 阶段 | 频率 |
|---|---|
| 扫描阶段 | 每 100 个文件 |
| 登记阶段 | 每 10 张图 |

（原设计为 500 / 50，优化后）

### 最后一批完成后的边界

```python
if (i + 1) < total and cancel_check and cancel_check():
    raise CancelledError()
只有还没处理完才检查取消。

如果所有登记已完成，用户再点取消，结果为 completed，不是 cancelled。

cancel_requested 的实现
简单 bool，不引入锁、Event。

## 6. CancelledError
定义在 core/scanner.py：

python
class CancelledError(Exception):
    """用户主动取消 Import。"""
    pass
语义： 只代表"用户主动取消"，不代表任何其他异常。

其他异常 → failed。


7. 进度信号
python
progress = Signal(int, object, int, int, int)
# (done, total_or_None, found, new, skip)
两阶段语义
阶段	done	total	found	new	skip
扫描	已扫描文件数	None	已发现图片数	0	0
登记	已登记数	实际发现数	实际发现数	累计新增	累计跳过
发送时机
时机	参数
扫描阶段每 100 文件	(n, None, found, 0, 0)
扫描结束	(file_count, None, found, 0, 0)
登记开始	(0, total, total, 0, 0)
登记阶段每 10 张	(n, total, total, new, skip)
登记结束	(total, total, total, new, skip)
8. add_image 异常处理
不吞掉异常。

情况	处理
正常返回 (id, True)	new_count += 1
正常返回 (id, False)	skip_count += 1
抛异常	Import 进入 failed（顶层 except Exception 处理）
9. finish_import_batch 失败处理
在 finally 里：

python
try:
    database.finish_import_batch(...)
    database.update_source_after_import(...)
except Exception as finish_err:
    print(f"[import] finish_import_batch 失败: {finish_err}", file=sys.stderr)
    if status == "completed":
        raise
语义：

status == "completed" → 收尾失败 → 抛异常（此时没有原始异常在传播）

status == "cancelled" 或 "failed" → 收尾失败不覆盖原始结果，打印到 stderr

10. 防呆统一入口
检查顺序
步骤	检查	结果
1	路径存在且是目录	不满足 → reject
2	盘符根目录（D:\）	是 → reject
3	图库根目录	是 → reject
4	图库内部	是 → reject
5	系统目录	是 → warn（可继续）
6	其他	ok
调用方
_validate_import_path(folder) 在：

import_external_folder（导入文件夹）

open_import_history（再次导入）

UI 和 scanner 各自独立检查（不因为 UI 检查过就跳过 scanner 的检查）。

11. 线程生命周期
MainWindow 持有 Worker / Dialog
python
self._import_worker = None
self._import_dialog = None
_run_import() 里赋值，dlg.exec() 返回后清理。

防重复启动
python
if self._import_worker is not None:
    return
MainWindow closeEvent
python
def closeEvent(self, event):
    if self._import_worker is not None:
        if self._import_worker.isRunning():
            self._import_worker.cancel()
            self._import_worker.wait()
    event.accept()
ImportProgressDialog 线程安全
方法	行为
_wait_for_worker()	只 wait()，不主动 cancel
closeEvent	忽略关闭，改为请求取消
keyPressEvent	忽略 Esc
on_finished	先 _wait_for_worker 再弹窗再关闭
on_failed	同上
on_cancel_clicked	worker.cancel()，按钮变"取消中…"
核心原则： _wait_for_worker() 返回时，worker 一定已经结束。

12. 移除来源
需求
从扫描区语义迁移：移除某个导入来源，同时移除该来源的未整理图片。

实现
database.get_source_stats(source_id) — 查询 external 图片数 + batch 数

database.remove_source_completely(source_id) — 删除顺序 images → batches → sources

ImportHistoryDialog 加"移除来源"按钮，带确认弹窗

移除后自动刷新"未整理"

关键约束
删除条件：

sql
WHERE storage_type = 'external'
  AND file_path LIKE '<source_path>\%'
已 Organize 成 managed 的图片不会被删。

删除顺序必须是：images → batches → sources。 否则触发外键约束失败。

13. 本阶段明确不做
预览会导入哪些文件

增量导入（只导新文件）

导入后"撤销整批"

拖拽文件夹导入

自动重试失败文件

多文件夹同时导入

断点续传

Worker Manager / QThreadPool / 任务队列

强制终止线程

复杂状态机

Import 事务系统

14. 未覆盖测试项
项	说明
扫描阶段取消	未直接验证。用户机器扫描速度较快，未能在扫描阶段稳定触发取消。代码路径已实现。
最后一张取消边界	未直接验证。手动触发极其困难。代码逻辑已实现（if (i+1) < total）。
这两项不构成封板阻塞项。