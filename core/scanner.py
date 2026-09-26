"""
文件扫描（Phase C：新模型）。
"""

import os

import config
import database


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}

ALBUM_NAME_MAX_CHARS = 8


def list_albums():
    lib = database.get_library()
    blacklist = set(database.get_blacklist_names())
    if not lib or not os.path.isdir(lib):
        return []

    albums = []
    for name in os.listdir(lib):
        full = os.path.join(lib, name)
        if not os.path.isdir(full):
            continue
        if name in ("data", "cache"):
            continue
        if name in blacklist:
            continue
        if len(name) > ALBUM_NAME_MAX_CHARS:
            database.add_to_blacklist(name)
            continue
        albums.append(name)
    return sorted(albums)


def scan_album_folder(album_name):
    lib = database.get_library()
    folder = os.path.join(lib, album_name)
    if not os.path.isdir(folder):
        return []

    result = []
    for root, _, files in os.walk(folder):
        for f in files:
            if os.path.splitext(f)[1].lower() in IMAGE_EXTS:
                result.append(os.path.join(root, f))
    return result


def scan_library_root_loose_files():
    lib = database.get_library()
    if not lib or not os.path.isdir(lib):
        return []

    result = []
    for name in os.listdir(lib):
        full = os.path.join(lib, name)
        if not os.path.isfile(full):
            continue
        if os.path.splitext(name)[1].lower() in IMAGE_EXTS:
            result.append(full)
    return result


def scan_blacklist_folders():
    lib = database.get_library()
    if not lib or not os.path.isdir(lib):
        return []

    blacklist = set(database.get_blacklist_names())
    result = []
    for name in blacklist:
        if name in ("data", "cache"):
            continue
        folder = os.path.join(lib, name)
        if not os.path.isdir(folder):
            continue
        for root, _, files in os.walk(folder):
            for f in files:
                if os.path.splitext(f)[1].lower() in IMAGE_EXTS:
                    result.append(os.path.join(root, f))
    return result


class CancelledError(Exception):
    """用户主动取消 Import。"""
    pass


def import_folder(folder_path, progress_callback=None, cancel_check=None):
    """
    一次性导入一个外部文件夹。

    progress_callback: (done, total, found, new, skip) -> None
      - 扫描阶段：done=已扫描文件数, total=None, found=已发现图片数, new=0, skip=0
      - 登记阶段：done=已登记数, total=found, found=found, new=累计新增, skip=累计跳过
    cancel_check: () -> bool，返回 True 表示请求取消

    返回 dict：
        {
            "status": "completed" / "cancelled",
            "total_found": int,
            "new_count": int,
            "skip_count": int,
            "batch_id": int,
            "source_id": int,
        }

    异常：
      - 路径不存在 → ValueError
      - 路径在图库内 → ValueError
      - 数据库异常 → 向上抛（status = "failed"）
    """
    folder_path = os.path.normpath(os.path.abspath(folder_path))
    library_root = database.get_library()

    if not os.path.isdir(folder_path):
        raise ValueError(f"文件夹不存在：{folder_path}")

    if library_root:
        lib_norm = os.path.normcase(os.path.normpath(library_root))
        folder_norm = os.path.normcase(folder_path)
        if folder_norm == lib_norm:
            raise ValueError(
                "不能把图库本身作为导入来源。\n"
                "图库内的图片会自动被识别为 managed，不需要导入。"
            )
        if folder_norm.startswith(lib_norm + os.sep):
            raise ValueError(
                f"不能导入图库内部的文件夹：\n{folder_path}\n"
                "图库内的图片会自动被识别为 managed，不需要导入。"
            )

    source_id = database.ensure_source(folder_path)
    batch_id = database.create_import_batch(source_id)

    status = "done"
    found_paths = []
    new_count = 0
    skip_count = 0
    file_count = 0

    try:
        # 阶段 A：扫描
        for root, _, files in os.walk(folder_path):
            for f in files:
                file_count += 1
                if os.path.splitext(f)[1].lower() in IMAGE_EXTS:
                    found_paths.append(os.path.join(root, f))

            if file_count % 100 == 0:
                if progress_callback:
                    progress_callback(
                        file_count, None, len(found_paths), 0, 0
                    )
                if cancel_check and cancel_check():
                    raise CancelledError()

        # 扫描结束，发一次最终扫描进度（total 仍为 None）
        if progress_callback:
            progress_callback(file_count, None, len(found_paths), 0, 0)

        # 阶段 B：登记
        total = len(found_paths)

        # 登记开始，发一次初始进度
        if progress_callback:
            progress_callback(0, total, total, 0, 0)

        for i, path in enumerate(found_paths):
            _, is_new = database.add_image(
                file_path=path,
                storage_type="external",
                organize_status="unsorted",
                album_rel_path=None,
            )
            if is_new:
                new_count += 1
            else:
                skip_count += 1

            if (i + 1) % 10 == 0:
                if progress_callback:
                    progress_callback(
                        i + 1, total, total, new_count, skip_count
                    )
                # 只有还没处理完才检查取消
                if (i + 1) < total and cancel_check and cancel_check():
                    raise CancelledError()

        # 登记结束，发一次最终进度
        if progress_callback:
            progress_callback(
                total, total, total, new_count, skip_count
            )

    except CancelledError:
        status = "cancelled"

    except Exception:
        status = "failed"
        raise

    finally:
        try:
            database.finish_import_batch(
                batch_id,
                total_found=len(found_paths),
                new_count=new_count,
                skip_count=skip_count,
                status=status,
            )
            database.update_source_after_import(source_id, new_count)
        except Exception as finish_err:
            import sys
            print(
                f"[import] finish_import_batch 失败: {finish_err}",
                file=sys.stderr,
            )
            if status == "completed":
                raise

    return {
        "status": status,
        "total_found": len(found_paths),
        "new_count": new_count,
        "skip_count": skip_count,
        "batch_id": batch_id,
        "source_id": source_id,
    }


def check_library():
    from PIL import Image
    from core.image_readers import init_image_readers

    init_image_readers()

    rows = database.get_all_images()
    total = len(rows)
    available = 0
    missing = 0
    unreadable = 0
    changed = 0

    for row in rows:
        real_path = database.get_real_path(row)
        old_status = row["file_status"]

        if not os.path.exists(real_path):
            new_status = "missing"
        else:
            try:
                with Image.open(real_path) as img:
                    img.verify()
                new_status = "available"
            except Exception:
                new_status = "unreadable"

        if new_status == "available":
            available += 1
        elif new_status == "missing":
            missing += 1
        else:
            unreadable += 1

        if new_status != old_status:
            changed += 1
            with database._connect() as conn:
                conn.execute(
                    "UPDATE images SET file_status = ? WHERE id = ?",
                    (new_status, row["id"])
                )
                conn.commit()

    return {
        "total": total,
        "available": available,
        "missing": missing,
        "unreadable": unreadable,
        "changed": changed,
    }


def is_drive_root(path):
    try:
        drive, tail = os.path.splitdrive(os.path.abspath(path))
        return bool(drive) and tail in ("\\", "/", "")
    except Exception:
        return False


_SYSTEM_DIR_HINTS = [
    "\\windows",
    "\\program files",
    "\\program files (x86)",
    "\\programdata",
    "\\$recycle.bin",
    "\\system volume information",
    "\\appdata",
    "\\node_modules",
    "\\.git",
    "\\__pycache__",
]


def is_system_dir(path):
    p = os.path.abspath(path).lower().replace("/", "\\")
    for hint in _SYSTEM_DIR_HINTS:
        if hint in p:
            return True
    return False


def estimate_directory_size(root, max_dirs=1000, max_files=10000):
    dir_count = 0
    file_count = 0
    hit_limit = False

    if not os.path.isdir(root):
        return 0, 0, False

    stack = [root]
    while stack:
        cur = stack.pop()
        try:
            entries = os.scandir(cur)
        except OSError:
            continue

        with entries:
            for entry in entries:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        dir_count += 1
                        stack.append(entry.path)
                    else:
                        file_count += 1
                except OSError:
                    continue

                if dir_count >= max_dirs or file_count >= max_files:
                    hit_limit = True
                    return dir_count, file_count, hit_limit

    return dir_count, file_count, hit_limit