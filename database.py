"""
数据库封装（Phase C：新模型）。
"""

import json
import os
import sqlite3
import time
from contextlib import contextmanager

import config

_current_library = None
_current_db = None


def set_library(library_path):
    global _current_library, _current_db
    _current_library = library_path
    _current_db = os.path.join(library_path, "data", "photo.db")
    os.makedirs(os.path.dirname(_current_db), exist_ok=True)


def get_library():
    return _current_library


def get_conn():
    if _current_db is None:
        raise RuntimeError("图库未设置")
    conn = sqlite3.connect(_current_db, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def _connect():
    conn = get_conn()
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    with _connect() as conn:
        cur = conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS images (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                storage_type      TEXT NOT NULL
                    CHECK (storage_type IN ('external', 'managed')),
                file_path         TEXT NOT NULL,
                filename          TEXT,
                size              INTEGER,
                modified_time     REAL,
                favorite          INTEGER DEFAULT 0,
                organize_status   TEXT NOT NULL
                    CHECK (organize_status IN ('unsorted', 'sorted')),
                file_status       TEXT NOT NULL
                    CHECK (file_status IN ('available', 'missing', 'unreadable')),
                added_time        REAL,
                album_added_time  REAL,
                month             TEXT,
                album_rel_path    TEXT
            )
        """)

        _ensure_column(cur, "images", "storage_type", "TEXT")
        _ensure_column(cur, "images", "organize_status", "TEXT")
        _ensure_column(cur, "images", "file_status", "TEXT")
        _ensure_column(cur, "images", "file_path", "TEXT")
        _ensure_column(cur, "images", "month", "TEXT")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS blacklist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                added_time REAL
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS operations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                op_type TEXT,
                src_path TEXT,
                dst_path TEXT,
                src_album TEXT,
                dst_album TEXT,
                timestamp REAL
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS album_covers (
                album_name TEXT PRIMARY KEY,
                cover_path TEXT
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS sources (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                path           TEXT UNIQUE NOT NULL,
                first_import   REAL,
                last_import    REAL,
                last_count     INTEGER
            )
        """)

        cur.execute("""
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
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_batches_source_id
                ON import_batches(source_id)
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS migration_state (
                id                 INTEGER PRIMARY KEY CHECK (id = 1),
                migration_version  INTEGER NOT NULL,
                current_stage      TEXT NOT NULL,
                started_at         REAL,
                updated_at         REAL
            )
        """)

        now = time.time()
        cur.executemany(
            "INSERT OR IGNORE INTO blacklist (name, added_time) VALUES (?, ?)",
            [("data", now), ("cache", now)]
        )

        conn.commit()


def _ensure_column(cur, table, column, decl):
    try:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
    except sqlite3.OperationalError:
        pass


def get_real_path(image_row):
    storage_type = image_row["storage_type"]
    file_path = image_row["file_path"]

    if storage_type == "external":
        return file_path
    elif storage_type == "managed":
        return os.path.join(_current_library, file_path)
    else:
        raise ValueError(f"未知 storage_type: {storage_type}")


def get_real_path_by_id(image_id):
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM images WHERE id = ?", (image_id,)
        ).fetchone()
    if row is None:
        return None
    return get_real_path(row)


def add_image(file_path, storage_type, organize_status,
              album_rel_path=None):
    now = time.time()

    if storage_type == "external":
        real_path = file_path
    else:
        real_path = os.path.join(_current_library, file_path)

    if not os.path.exists(real_path):
        file_status = "missing"
    else:
        file_status = "available"

    try:
        stat = os.stat(real_path)
        size = stat.st_size
        modified_time = stat.st_mtime
    except OSError:
        size = 0
        modified_time = 0

    filename = os.path.basename(real_path)

    with _connect() as conn:
        row = conn.execute(
            "SELECT id FROM images WHERE storage_type = ? AND file_path = ?",
            (storage_type, file_path)
        ).fetchone()
        if row is not None:
            return row["id"], False

        cur = conn.execute(
            """INSERT INTO images
               (storage_type, file_path, filename, size, modified_time,
                organize_status, file_status, added_time, album_rel_path)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (storage_type, file_path, filename, size, modified_time,
             organize_status, file_status, now, album_rel_path)
        )
        conn.commit()
        return cur.lastrowid, True


def add_images_batch(records):
    now = time.time()
    new_ids = []
    skip_count = 0

    with _connect() as conn:
        for rec in records:
            storage_type = rec["storage_type"]
            file_path = rec["file_path"]
            organize_status = rec["organize_status"]
            album_rel_path = rec.get("album_rel_path")

            if storage_type == "external":
                real_path = file_path
            else:
                real_path = os.path.join(_current_library, file_path)

            if not os.path.exists(real_path):
                file_status = "missing"
            else:
                file_status = "available"

            try:
                stat = os.stat(real_path)
                size = stat.st_size
                modified_time = stat.st_mtime
            except OSError:
                size = 0
                modified_time = 0

            filename = os.path.basename(real_path)

            row = conn.execute(
                "SELECT id FROM images WHERE storage_type = ? AND file_path = ?",
                (storage_type, file_path)
            ).fetchone()
            if row is not None:
                skip_count += 1
                continue

            cur = conn.execute(
                """INSERT INTO images
                   (storage_type, file_path, filename, size, modified_time,
                    organize_status, file_status, added_time, album_rel_path)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (storage_type, file_path, filename, size, modified_time,
                 organize_status, file_status, now, album_rel_path)
            )
            new_ids.append(cur.lastrowid)

        conn.commit()

    return new_ids, skip_count


def _query_images(sql, params=()):
    with _connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def get_all_images():
    return _query_images("SELECT * FROM images ORDER BY added_time DESC")


def get_unsorted_images():
    return _query_images(
        "SELECT * FROM images WHERE organize_status = 'unsorted' "
        "ORDER BY added_time DESC"
    )


def get_sorted_images():
    return _query_images(
        "SELECT * FROM images WHERE organize_status = 'sorted' "
        "ORDER BY album_added_time DESC, added_time DESC"
    )


def get_album_images(album_name):
    if album_name is None:
        return []
    prefix = album_name + os.sep
    return _query_images(
        "SELECT * FROM images "
        "WHERE storage_type = 'managed' "
        "  AND file_path LIKE ? "
        "  AND file_path NOT LIKE ? "
        "ORDER BY album_added_time DESC, added_time DESC",
        (prefix + "%", prefix + "%" + os.sep + "%")
    )


def get_favorites():
    return _query_images(
        "SELECT * FROM images WHERE favorite = 1 ORDER BY added_time DESC"
    )


def get_image_by_id(image_id):
    rows = _query_images("SELECT * FROM images WHERE id = ?", (image_id,))
    return rows[0] if rows else None


def get_image_by_path(file_path, storage_type):
    rows = _query_images(
        "SELECT * FROM images WHERE file_path = ? AND storage_type = ?",
        (file_path, storage_type)
    )
    return rows[0] if rows else None


def count_images():
    with _connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM images").fetchone()[0]


def count_unsorted():
    with _connect() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM images WHERE organize_status = 'unsorted'"
        ).fetchone()[0]


def set_favorite(image_id, fav):
    with _connect() as conn:
        conn.execute(
            "UPDATE images SET favorite = ? WHERE id = ?",
            (1 if fav else 0, image_id)
        )
        conn.commit()


def is_favorite(image_id):
    with _connect() as conn:
        row = conn.execute(
            "SELECT favorite FROM images WHERE id = ?", (image_id,)
        ).fetchone()
    return bool(row["favorite"]) if row else False


def get_blacklist_names():
    with _connect() as conn:
        rows = conn.execute("SELECT name FROM blacklist").fetchall()
    return [r["name"] for r in rows]


def add_to_blacklist(name):
    with _connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO blacklist (name, added_time) VALUES (?, ?)",
            (name, time.time())
        )
        conn.commit()


def remove_from_blacklist(name):
    with _connect() as conn:
        conn.execute("DELETE FROM blacklist WHERE name = ?", (name,))
        conn.commit()


def _normalize_path_arg(value):
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=False)
    return value


def record_operation(op_type, src_path, dst_path,
                     src_album=None, dst_album=None):
    src_path = _normalize_path_arg(src_path)
    dst_path = _normalize_path_arg(dst_path)

    with _connect() as conn:
        conn.execute(
            """INSERT INTO operations
               (op_type, src_path, dst_path, src_album, dst_album, timestamp)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (op_type, src_path, dst_path, src_album, dst_album, time.time())
        )
        conn.execute("""
            DELETE FROM operations WHERE id NOT IN (
                SELECT id FROM operations ORDER BY id DESC LIMIT 10
            )
        """)
        conn.commit()


def pop_last_operation():
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM operations ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        conn.execute("DELETE FROM operations WHERE id = ?", (row["id"],))
        conn.commit()
        return dict(row)


def update_image_path(image_id, new_storage_type, new_file_path,
                      new_organize_status=None, new_album_rel_path=None):
    now = time.time()

    if new_storage_type == "external":
        real_path = new_file_path
    else:
        real_path = os.path.join(_current_library, new_file_path)

    filename = os.path.basename(real_path)
    try:
        stat = os.stat(real_path)
        size = stat.st_size
        modified_time = stat.st_mtime
    except OSError:
        size = 0
        modified_time = 0

    with _connect() as conn:
        if new_organize_status is not None:
            conn.execute(
                """UPDATE images SET
                   storage_type = ?, file_path = ?, filename = ?,
                   size = ?, modified_time = ?,
                   organize_status = ?, album_rel_path = ?,
                   album_added_time = ?
                   WHERE id = ?""",
                (new_storage_type, new_file_path, filename,
                 size, modified_time,
                 new_organize_status, new_album_rel_path,
                 now, image_id)
            )
        else:
            conn.execute(
                """UPDATE images SET
                   storage_type = ?, file_path = ?, filename = ?,
                   size = ?, modified_time = ?,
                   album_rel_path = ?
                   WHERE id = ?""",
                (new_storage_type, new_file_path, filename,
                 size, modified_time,
                 new_album_rel_path, image_id)
            )
        conn.commit()


def delete_image_record(image_id):
    with _connect() as conn:
        conn.execute("DELETE FROM images WHERE id = ?", (image_id,))
        conn.commit()


def get_image_months(image_ids):
    if not image_ids:
        return {}
    result = {}
    with _connect() as conn:
        CHUNK = 500
        for i in range(0, len(image_ids), CHUNK):
            chunk = image_ids[i:i + CHUNK]
            placeholders = ",".join("?" * len(chunk))
            rows = conn.execute(
                f"SELECT id, month FROM images WHERE id IN ({placeholders})",
                chunk
            ).fetchall()
            for r in rows:
                result[r["id"]] = r["month"]
    for i in image_ids:
        result.setdefault(i, None)
    return result


def set_image_month(image_id, month):
    with _connect() as conn:
        conn.execute(
            "UPDATE images SET month = ? WHERE id = ?",
            (month, image_id)
        )
        conn.commit()


def set_album_cover(album_name, cover_path):
    with _connect() as conn:
        conn.execute(
            """INSERT INTO album_covers (album_name, cover_path)
               VALUES (?, ?)
               ON CONFLICT(album_name) DO UPDATE SET
                 cover_path = excluded.cover_path""",
            (album_name, cover_path)
        )
        conn.commit()


def get_album_cover_manual(album_name):
    with _connect() as conn:
        row = conn.execute(
            "SELECT cover_path FROM album_covers WHERE album_name = ?",
            (album_name,)
        ).fetchone()
    return row["cover_path"] if row else None


def rename_album_cover(old_name, new_name):
    with _connect() as conn:
        conn.execute(
            "UPDATE album_covers SET album_name = ? WHERE album_name = ?",
            (new_name, old_name)
        )
        conn.commit()


def delete_album_cover(album_name):
    with _connect() as conn:
        conn.execute(
            "DELETE FROM album_covers WHERE album_name = ?", (album_name,)
        )
        conn.commit()


def get_album_cover(album_name):
    with _connect() as conn:
        row = conn.execute(
            """SELECT file_path, storage_type FROM images
               WHERE storage_type = 'managed'
                 AND file_path LIKE ?
               ORDER BY album_added_time DESC, added_time DESC
               LIMIT 1""",
            (album_name + os.sep + "%",)
        ).fetchone()
    if row is None:
        return None
    if row["storage_type"] == "managed":
        return os.path.join(_current_library, row["file_path"])
    return row["file_path"]


def get_album_of_path(file_path, storage_type):
    if storage_type != "managed":
        return None
    parts = file_path.replace("/", os.sep).split(os.sep)
    if len(parts) <= 1:
        return None
    return parts[0]


def rename_album_records(old_name, new_name):
    old_prefix = old_name + os.sep
    new_prefix = new_name + os.sep

    with _connect() as conn:
        rows = conn.execute(
            """SELECT id, file_path FROM images
               WHERE storage_type = 'managed'
                 AND file_path LIKE ?""",
            (old_prefix + "%",)
        ).fetchall()
        for row in rows:
            new_path = new_prefix + row["file_path"][len(old_prefix):]
            conn.execute(
                "UPDATE images SET file_path = ? WHERE id = ?",
                (new_path, row["id"])
            )
        conn.commit()


def delete_album_records(album_name):
    prefix = album_name + os.sep
    with _connect() as conn:
        conn.execute(
            """DELETE FROM images
               WHERE storage_type = 'managed'
                 AND file_path LIKE ?""",
            (prefix + "%",)
        )
        conn.commit()


def ensure_source(path):
    now = time.time()
    with _connect() as conn:
        row = conn.execute(
            "SELECT id FROM sources WHERE path = ?", (path,)
        ).fetchone()
        if row is not None:
            return row["id"]

        cur = conn.execute(
            "INSERT INTO sources (path, first_import) VALUES (?, ?)",
            (path, now)
        )
        conn.commit()
        return cur.lastrowid


def update_source_after_import(source_id, count):
    with _connect() as conn:
        conn.execute(
            """UPDATE sources
               SET last_import = ?, last_count = ?
               WHERE id = ?""",
            (time.time(), count, source_id)
        )
        conn.commit()


def create_import_batch(source_id):
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO import_batches
               (source_id, start_time, status)
               VALUES (?, ?, 'running')""",
            (source_id, time.time())
        )
        conn.commit()
        return cur.lastrowid


def finish_import_batch(batch_id, total_found, new_count, skip_count,
                        status="done"):
    with _connect() as conn:
        conn.execute(
            """UPDATE import_batches
               SET end_time = ?, total_found = ?, new_count = ?,
                   skip_count = ?, status = ?
               WHERE id = ?""",
            (time.time(), total_found, new_count, skip_count,
             status, batch_id)
        )
        conn.commit()


def get_sources():
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM sources ORDER BY last_import DESC"
        ).fetchall()
    return [dict(r) for r in rows]

def get_source_stats(source_id):
    """
    查询某个 source 的统计：
      - external_count：该 source 对应的未整理图片记录数
      - batch_count：该 source 的导入批次数量
    """
    with _connect() as conn:
        # 该 source 的路径
        row = conn.execute(
            "SELECT path FROM sources WHERE id = ?", (source_id,)
        ).fetchone()
        if row is None:
            return None
        source_path = row["path"]

        external_count = conn.execute(
            "SELECT COUNT(*) FROM images "
            "WHERE storage_type = 'external' AND file_path LIKE ?",
            (source_path + os.sep + "%",)
        ).fetchone()[0]

        batch_count = conn.execute(
            "SELECT COUNT(*) FROM import_batches WHERE source_id = ?",
            (source_id,)
        ).fetchone()[0]

    return {
        "external_count": external_count,
        "batch_count": batch_count,
        "source_path": source_path,
    }


def remove_source_completely(source_id):
    """
    完全移除一个 source：
      1. 删除该 source 下所有 external 图片记录
      2. 删除该 source 的所有 import_batches
      3. 删除该 source 本身

    不动磁盘文件。
    不动 managed 图片。

    返回 dict：
        {
            "deleted_images": int,
            "deleted_batches": int,
            "deleted_source": bool,
        }

    注意：删除顺序必须是 images → batches → sources，
    否则会触发外键约束失败。
    """
    with _connect() as conn:
        # 查 source 路径
        row = conn.execute(
            "SELECT path FROM sources WHERE id = ?", (source_id,)
        ).fetchone()
        if row is None:
            return {
                "deleted_images": 0,
                "deleted_batches": 0,
                "deleted_source": False,
            }
        source_path = row["path"]

        # 1. 删除 external 图片（只删这个 source 的）
        cur = conn.execute(
            "DELETE FROM images "
            "WHERE storage_type = 'external' AND file_path LIKE ?",
            (source_path + os.sep + "%",)
        )
        deleted_images = cur.rowcount

        # 2. 删除 batches
        cur = conn.execute(
            "DELETE FROM import_batches WHERE source_id = ?",
            (source_id,)
        )
        deleted_batches = cur.rowcount

        # 3. 删除 source
        cur = conn.execute(
            "DELETE FROM sources WHERE id = ?",
            (source_id,)
        )
        deleted_source = cur.rowcount > 0

        conn.commit()

    return {
        "deleted_images": deleted_images,
        "deleted_batches": deleted_batches,
        "deleted_source": deleted_source,
    }


def get_import_batches(source_id=None):
    with _connect() as conn:
        if source_id is None:
            rows = conn.execute(
                "SELECT * FROM import_batches ORDER BY start_time DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM import_batches WHERE source_id = ? "
                "ORDER BY start_time DESC",
                (source_id,)
            ).fetchall()
    return [dict(r) for r in rows]


def fix_stale_running_batches():
    with _connect() as conn:
        cur = conn.execute(
            """UPDATE import_batches
               SET status = 'failed', end_time = ?
               WHERE status = 'running'""",
            (time.time(),)
        )
        conn.commit()
        return cur.rowcount


def backup_database(keep=5):
    if _current_db is None:
        return False, "图库未设置"

    if not os.path.exists(_current_db):
        return False, "数据库文件不存在"

    backup_dir = os.path.join(_current_library, "data", "backup")
    os.makedirs(backup_dir, exist_ok=True)

    ts = time.strftime("%Y%m%d_%H%M%S")
    backup_name = f"photo_{ts}.db"
    backup_path = os.path.join(backup_dir, backup_name)

    src = sqlite3.connect(_current_db)
    try:
        dst = sqlite3.connect(backup_path)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()

    try:
        files = []
        for name in os.listdir(backup_dir):
            if not name.startswith("photo_") or not name.endswith(".db"):
                continue
            full = os.path.join(backup_dir, name)
            if os.path.isfile(full):
                files.append((os.path.getmtime(full), full))
        files.sort(reverse=True)
        for _, full in files[keep:]:
            try:
                os.remove(full)
            except Exception:
                pass
    except Exception:
        pass

    return True, backup_path


if __name__ == "__main__":
    print("database.py 是模块，不能直接运行。请运行 main.py。")