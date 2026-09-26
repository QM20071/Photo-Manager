"""
Phase 1 数据迁移脚本。

把旧模型的数据转换成新模型：
  - images 表新增 storage_type / organize_status / file_status / file_path_new
  - config.json 的 scan_paths 迁移到 sources 表
  - config.json 删除 scan_paths

安全底线（Migration Safety Rule #1）：
    本脚本不得对任何原始图片文件执行移动、重命名、删除、覆盖或写入操作。
    所有图片文件一律只读。

symlink 语义：
    - is_in_library() 按字面路径判断，不解析 symlink。
    - file_status 对已存在的历史图片路径，按操作系统实际打开结果判断可读性。
    - 迁移过程不主动遍历或追踪 symlink。

设计依据：
    《Phase 1 数据模型设计文档 v2》第 5 节（已冻结）。

使用方式：
    python migrate.py
"""

import json
import os
import sqlite3
import time

from PIL import Image

# 统一图片读取初始化（含 HEIF 支持）
from core.image_readers import init_image_readers


# ============================================================
# 常量
# ============================================================

MIGRATION_VERSION = 1

STAGE_NOT_STARTED = "not_started"
STAGE_PHASE_A_DONE = "phase_a_done"
STAGE_PHASE_B_DONE = "phase_b_done"
STAGE_SOURCES_DONE = "sources_done"
STAGE_CONFIG_DONE = "config_done"
STAGE_COMPLETED = "completed"

ALL_STAGES = [
    STAGE_NOT_STARTED,
    STAGE_PHASE_A_DONE,
    STAGE_PHASE_B_DONE,
    STAGE_SOURCES_DONE,
    STAGE_CONFIG_DONE,
    STAGE_COMPLETED,
]

NEW_COLUMNS = [
    ("storage_type", "TEXT"),
    ("organize_status", "TEXT"),
    ("file_status", "TEXT"),
    ("file_path_new", "TEXT"),
]


# ============================================================
# 配置读取
# ============================================================

def app_dir():
    return os.path.dirname(os.path.abspath(__file__))


def default_config_path():
    return os.path.join(app_dir(), "config.json")


def load_config(config_path):
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"找不到 config.json: {config_path}")
    with open(config_path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def save_config_safely(config_path, new_config):
    """
    安全写入 config.json：
      临时文件 → 完整写入 → fsync → os.replace 原子替换。
    """
    tmp_path = config_path + ".tmp"

    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(new_config, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())

    os.replace(tmp_path, config_path)


# ============================================================
# 路径处理
# ============================================================

def normalize_path(p):
    """返回存储值：保留大小写的规范化路径。"""
    return os.path.normpath(os.path.abspath(p))


def comparison_key(p):
    """返回比较值：Windows 下大小写无关的规范化路径。"""
    return os.path.normcase(normalize_path(p))


def is_in_library(path, library_root):
    """
    判断 path 是否在 library_root 内。
      - 用字面路径判断，不解析 symlink
      - library_root 本身不算
      - Windows 大小写无关
    """
    key_path = comparison_key(path)
    key_root = comparison_key(library_root)

    if key_path == key_root:
        return False
    if not key_path.startswith(key_root + os.sep):
        return False
    return True


def lexically_relative_to(path, root):
    """
    纯词法相对路径计算。
      - 不解析 symlink
      - 前提：is_in_library(path, root) 已经返回 True
    """
    normalized_path = normalize_path(path)
    normalized_root = normalize_path(root)

    key_path = comparison_key(normalized_path)
    key_root = comparison_key(normalized_root)

    if not key_path.startswith(key_root + os.sep):
        raise ValueError(
            f"lexically_relative_to: {path!r} 不在 {root!r} 内"
        )

    return normalized_path[len(normalized_root) + 1:]


# ============================================================
# 图片可读性检查
# ============================================================

def is_image_readable(path):
    """
    判断图片能否被当前支持的读取机制打开。
      - 用 Image.open + verify
      - 不因为 EXIF 损坏而返回 False
      - 对 symlink：由操作系统实际打开结果决定
    """
    try:
        with Image.open(path) as img:
            img.verify()
        return True
    except Exception:
        return False


# ============================================================
# 字段计算
# ============================================================

def compute_storage_type(path, library_root):
    if is_in_library(path, library_root):
        return "managed"
    return "external"


def compute_file_path_new(path, library_root, storage_type):
    if storage_type == "managed":
        return lexically_relative_to(path, library_root)
    return normalize_path(path)


def compute_organize_status(album_rel_path):
    if album_rel_path is None or album_rel_path == "":
        return "unsorted"
    return "sorted"


def compute_file_status(storage_type, file_path_new, library_root):
    if storage_type == "managed":
        real_path = os.path.join(library_root, file_path_new)
    else:
        real_path = file_path_new

    if not os.path.exists(real_path):
        return "missing"
    if is_image_readable(real_path):
        return "available"
    return "unreadable"


# ============================================================
# migration_state 表操作
# ============================================================

def ensure_migration_state_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS migration_state (
            id                 INTEGER PRIMARY KEY CHECK (id = 1),
            migration_version  INTEGER NOT NULL,
            current_stage      TEXT NOT NULL
                CHECK (current_stage IN (
                    'not_started',
                    'phase_a_done',
                    'phase_b_done',
                    'sources_done',
                    'config_done',
                    'completed'
                )),
            started_at         REAL,
            updated_at         REAL
        )
    """)
    conn.commit()


def read_migration_state(conn):
    """返回 (migration_version, current_stage)；无记录返回 (None, None)。"""
    try:
        row = conn.execute(
            "SELECT migration_version, current_stage "
            "FROM migration_state WHERE id = 1"
        ).fetchone()
    except sqlite3.OperationalError:
        return None, None
    if row is None:
        return None, None
    return row[0], row[1]


def check_migration_version(conn):
    """
    返回 (state_exists, stage)。
      - state 不存在 → (False, None)
      - version 匹配 → (True, current_stage)
      - version 不匹配 → 抛异常
    """
    version, stage = read_migration_state(conn)
    if version is None:
        return False, None
    if version != MIGRATION_VERSION:
        raise RuntimeError(
            f"migration_version 不匹配：数据库里是 {version}，"
            f"当前脚本是 {MIGRATION_VERSION}。拒绝继续。"
        )
    return True, stage


def init_migration_state(conn):
    now = time.time()
    conn.execute("""
        INSERT OR IGNORE INTO migration_state
        (id, migration_version, current_stage, started_at, updated_at)
        VALUES (1, ?, ?, ?, ?)
    """, (MIGRATION_VERSION, STAGE_NOT_STARTED, now, now))
    conn.commit()


def set_stage(conn, stage):
    if stage not in ALL_STAGES:
        raise ValueError(f"非法阶段: {stage}")
    conn.execute("""
        UPDATE migration_state
        SET current_stage = ?, updated_at = ?
        WHERE id = 1
    """, (stage, time.time()))
    conn.commit()


# ============================================================
# 备份
# ============================================================

def backup_sqlite_db(src_db_path, dst_db_path):
    """
    用 SQLite backup API 备份数据库。
    正确处理 WAL 模式。
    """
    src = sqlite3.connect(src_db_path)
    try:
        dst = sqlite3.connect(dst_db_path)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def ensure_backup(db_path, config_path, migration_version):
    """
    备份 photo.db 和 config.json。每个 migration_version 只做一次。
    只有 DB + config 都成功后才写 marker。
    """
    marker = os.path.join(
        os.path.dirname(db_path),
        f".backup_v{migration_version}.done"
    )
    if os.path.exists(marker):
        print(f"  [backup] 已存在备份标记，跳过")
        return

    backup_dir = os.path.join(os.path.dirname(db_path), "backup")
    os.makedirs(backup_dir, exist_ok=True)

    ts = time.strftime("%Y%m%d_%H%M%S")

    db_backup = os.path.join(
        backup_dir, f"photo_pre_v{migration_version}_{ts}.db"
    )
    backup_sqlite_db(db_path, db_backup)
    print(f"  [backup] 数据库 → {db_backup}")

    if os.path.exists(config_path):
        cfg_backup = config_path + f".pre_v{migration_version}.{ts}.bak"
        with open(config_path, "rb") as src, open(cfg_backup, "wb") as dst:
            dst.write(src.read())
        print(f"  [backup] config → {cfg_backup}")

    with open(marker, "w", encoding="utf-8") as f:
        f.write(str(time.time()))
    print(f"  [backup] 标记 → {marker}")


# ============================================================
# Phase A：加列
# ============================================================

def column_exists(conn, table, column):
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row[1] == column for row in rows)


def add_columns(conn):
    """Phase A：给 images 表加新列。幂等。"""
    print("  [Phase A] 检查并添加新列...")
    for col_name, col_type in NEW_COLUMNS:
        if column_exists(conn, "images", col_name):
            print(f"    - {col_name} 已存在，跳过")
            continue
        conn.execute(f"ALTER TABLE images ADD COLUMN {col_name} {col_type}")
        print(f"    - {col_name} 已添加")
    conn.commit()


# ============================================================
# Phase B：填充新字段
# ============================================================

def phase_b(conn, library_root):
    """
    Phase B：先计算全部新值（事务外），再一个事务批量写入。
    幂等：重跑时重新计算所有行。
    """
    print("  [Phase B] 读取旧数据...")
    rows = conn.execute(
        "SELECT id, path, album_rel_path FROM images"
    ).fetchall()
    print(f"  [Phase B] 共 {len(rows)} 行，开始计算...")

    updates = []
    for i, row in enumerate(rows):
        image_id = row["id"]
        path = row["path"]
        album_rel_path = row["album_rel_path"]

        storage_type = compute_storage_type(path, library_root)
        file_path_new = compute_file_path_new(path, library_root, storage_type)
        organize_status = compute_organize_status(album_rel_path)
        file_status = compute_file_status(
            storage_type, file_path_new, library_root
        )

        updates.append((
            storage_type, organize_status, file_status,
            file_path_new, image_id
        ))

        if (i + 1) % 1000 == 0:
            print(f"    计算进度 {i + 1} / {len(rows)}")

    print(f"  [Phase B] 计算完成，开始写入数据库...")
    conn.execute("BEGIN")
    conn.executemany("""
        UPDATE images SET
            storage_type = ?,
            organize_status = ?,
            file_status = ?,
            file_path_new = ?
        WHERE id = ?
    """, updates)
    conn.commit()
    print(f"  [Phase B] 已写入 {len(updates)} 行")


# ============================================================
# 验证
# ============================================================

def verify_phase_b_integrity(conn):
    """
    Phase B 后的完整性验证（不做 warning 统计）。
      - 新字段全部非空
      - file_path_new 无重复
    """
    print("  [验证] 检查新字段完整性...")

    null_count = conn.execute("""
        SELECT COUNT(*) FROM images
        WHERE storage_type IS NULL
           OR organize_status IS NULL
           OR file_status IS NULL
           OR file_path_new IS NULL
    """).fetchone()[0]

    if null_count > 0:
        raise Exception(f"有 {null_count} 行的新字段仍为 NULL")

    print("  [验证] 检查 file_path_new 唯一性...")
    rows = conn.execute("SELECT id, file_path_new FROM images").fetchall()
    seen = {}
    for row in rows:
        key = os.path.normcase(row["file_path_new"])
        if key in seen:
            raise Exception(
                f"file_path_new 冲突：id={row['id']} 和 id={seen[key]} "
                f"都指向 {row['file_path_new']}"
            )
        seen[key] = row["id"]


def report_history_warnings(conn):
    """
    检查 external + sorted 历史异常，返回 warning_count。
    """
    abnormal = conn.execute("""
        SELECT id, path, album_rel_path FROM images
        WHERE storage_type = 'external' AND organize_status = 'sorted'
    """).fetchall()

    warning_count = len(abnormal)
    if warning_count > 0:
        print(f"  [警告] 发现 {warning_count} 条 external + sorted 历史异常：")
        for row in abnormal[:10]:
            print(f"    id={row['id']}  path={row['path']}  "
                  f"album={row['album_rel_path']}")
        if warning_count > 10:
            print(f"    ... 还有 {warning_count - 10} 条")
    else:
        print("  [验证] 无历史异常数据")

    return warning_count


# ============================================================
# sources 迁移
# ============================================================

def ensure_sources_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sources (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            path           TEXT UNIQUE NOT NULL,
            first_import   REAL,
            last_import    REAL,
            last_count     INTEGER
        )
    """)
    conn.commit()


def ensure_import_batches_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS import_batches (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id      INTEGER NOT NULL,
            start_time     REAL,
            end_time       REAL,
            total_found    INTEGER,
            new_count      INTEGER,
            skip_count     INTEGER,
            status         TEXT NOT NULL
                CHECK (status IN ('running', 'done', 'failed', 'cancelled')),
            FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE RESTRICT
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_batches_source_id
            ON import_batches(source_id)
    """)
    conn.commit()


def migrate_scan_paths_to_sources(config, conn):
    """把 config.json 的 scan_paths 迁移到 sources 表。"""
    print("  [sources] 迁移 scan_paths...")

    scan_paths = config.get("scan_paths", [])
    if not scan_paths:
        print("    scan_paths 为空，跳过")
        return

    now = time.time()
    seen = set()
    inserted = 0

    for raw_path in scan_paths:
        try:
            normalized = normalize_path(raw_path)
        except Exception as e:
            print(f"    [警告] 无法规范化 {raw_path!r}：{e}")
            continue

        key = os.path.normcase(normalized)
        if key in seen:
            print(f"    - 跳过重复：{normalized}")
            continue
        seen.add(key)

        cur = conn.execute("""
            INSERT OR IGNORE INTO sources
            (path, first_import, last_import, last_count)
            VALUES (?, ?, NULL, NULL)
        """, (normalized, now))

        if cur.rowcount > 0:
            inserted += 1
            print(f"    + {normalized}")
        else:
            print(f"    - 已存在：{normalized}")

    conn.commit()
    print(f"  [sources] 新增 {inserted} 条")


# ============================================================
# config 迁移
# ============================================================

def migrate_config(config_path, config):
    """删除 config.json 中的 scan_paths。"""
    print("  [config] 移除 scan_paths...")

    if "scan_paths" not in config:
        print("    config.json 中没有 scan_paths，跳过")
        return

    new_config = dict(config)
    new_config.pop("scan_paths", None)
    save_config_safely(config_path, new_config)
    print("  [config] 已保存")


# ============================================================
# 主流程
# ============================================================

def main():
    # 统一初始化图片读取支持（含 HEIF）
    init_image_readers()

    print("=" * 60)
    print("Phase 1 数据迁移")
    print("=" * 60)

    config_path = default_config_path()

    config = load_config(config_path)
    library_root = config.get("library_path")
    if not library_root:
        print("错误：config.json 中没有 library_path")
        return

    db_path = os.path.join(library_root, "data", "photo.db")
    if not os.path.exists(db_path):
        print(f"错误：找不到数据库 {db_path}")
        return

    print(f"图库: {library_root}")
    print(f"数据库: {db_path}")
    print()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    warning_count = 0

    try:
        state_exists, stage = check_migration_version(conn)

        if not state_exists:
            print("首次运行，执行备份...")
            print()
            ensure_backup(db_path, config_path, MIGRATION_VERSION)
            ensure_migration_state_table(conn)
            init_migration_state(conn)
            stage = STAGE_NOT_STARTED
            print()
        else:
            print(f"当前阶段: {stage}")
            print()

        if stage == STAGE_COMPLETED:
            print("迁移已完成，无需重复执行")
            return

        if stage == STAGE_NOT_STARTED:
            print(">>> Phase A：加列")
            add_columns(conn)
            set_stage(conn, STAGE_PHASE_A_DONE)
            stage = STAGE_PHASE_A_DONE
            print()

        if stage == STAGE_PHASE_A_DONE:
            print(">>> Phase B：填充新字段")
            phase_b(conn, library_root)
            verify_phase_b_integrity(conn)
            report_history_warnings(conn)
            set_stage(conn, STAGE_PHASE_B_DONE)
            stage = STAGE_PHASE_B_DONE
            print()

        if stage == STAGE_PHASE_B_DONE:
            print(">>> 建立 sources / import_batches 表")
            ensure_sources_table(conn)
            ensure_import_batches_table(conn)
            print()
            print(">>> 迁移 scan_paths 到 sources")
            migrate_scan_paths_to_sources(config, conn)
            set_stage(conn, STAGE_SOURCES_DONE)
            stage = STAGE_SOURCES_DONE
            print()

        if stage == STAGE_SOURCES_DONE:
            print(">>> 迁移 config.json")
            migrate_config(config_path, config)
            set_stage(conn, STAGE_CONFIG_DONE)
            stage = STAGE_CONFIG_DONE
            print()

        if stage == STAGE_CONFIG_DONE:
            print(">>> 最终检查")
            warning_count = report_history_warnings(conn)
            print()
            set_stage(conn, STAGE_COMPLETED)
            print(">>> 迁移完成")
            print()

    finally:
        conn.close()

    print("=" * 60)
    if warning_count > 0:
        print(f"迁移完成，但存在 {warning_count} 条历史数据警告")
        print("（详见上方 [警告] 部分）")
    else:
        print("迁移成功")
    print("=" * 60)


if __name__ == "__main__":
    main()