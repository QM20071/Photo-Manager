"""
文件操作统一入口（Phase C：新模型）。
"""

import os
import secrets
import shutil

import database


RESULT_SUCCESS = "SUCCESS"
RESULT_FAILED = "FAILED"
RESULT_PARTIAL = "PARTIAL"


def _same_filesystem(src, dst_dir):
    try:
        src_dev = os.stat(os.path.dirname(src)).st_dev
        dst_dev = os.stat(dst_dir).st_dev
        return src_dev == dst_dev
    except OSError:
        return False


def _unique_target(dst_dir, base_name):
    name, ext = os.path.splitext(base_name)
    target = os.path.join(dst_dir, base_name)

    counter = 1
    while os.path.exists(target):
        target = os.path.join(dst_dir, f"{name}({counter}){ext}")
        counter += 1
        if counter > 1000:
            raise RuntimeError("重名过多")
    return target


def _make_temp_path(final_path):
    dirname = os.path.dirname(final_path)
    basename = os.path.basename(final_path)
    suffix = secrets.token_hex(4)
    return os.path.join(dirname, f"{basename}.tmp_{suffix}")


def _try_remove(path):
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


def _move_same_fs(src, dst_dir):
    if not os.path.exists(src):
        return RESULT_FAILED, "源文件不存在"

    try:
        os.makedirs(dst_dir, exist_ok=True)
    except Exception as e:
        return RESULT_FAILED, f"无法创建目标目录：{e}"

    base_name = os.path.basename(src)
    try:
        target = _unique_target(dst_dir, base_name)
    except RuntimeError as e:
        return RESULT_FAILED, str(e)

    try:
        os.rename(src, target)
    except Exception as e:
        return RESULT_FAILED, f"rename 失败：{e}"

    return RESULT_SUCCESS, target


def _move_cross_fs(src, dst_dir):
    if not os.path.exists(src):
        return RESULT_FAILED, "源文件不存在"

    try:
        os.makedirs(dst_dir, exist_ok=True)
    except Exception as e:
        return RESULT_FAILED, f"无法创建目标目录：{e}"

    base_name = os.path.basename(src)
    try:
        final_path = _unique_target(dst_dir, base_name)
    except RuntimeError as e:
        return RESULT_FAILED, str(e)

    temp_path = _make_temp_path(final_path)

    try:
        shutil.copy2(src, temp_path)
    except Exception as e:
        _try_remove(temp_path)
        return RESULT_FAILED, f"复制失败：{e}"

    try:
        src_size = os.path.getsize(src)
        temp_size = os.path.getsize(temp_path)
    except OSError as e:
        _try_remove(temp_path)
        return RESULT_FAILED, f"无法读取文件大小：{e}"

    if src_size != temp_size:
        _try_remove(temp_path)
        return RESULT_FAILED, (
            f"复制不完整（源 {src_size} 字节，目标 {temp_size} 字节）"
        )

    try:
        os.rename(temp_path, final_path)
    except Exception as e:
        _try_remove(temp_path)
        return RESULT_FAILED, f"temp→final 失败：{e}"

    try:
        os.remove(src)
    except Exception as e:
        return RESULT_PARTIAL, (
            f"文件已复制到 {final_path}，但源文件删除失败：{e}"
        )

    return RESULT_SUCCESS, final_path


def _move_physical(src, dst_dir):
    if not os.path.exists(src):
        return RESULT_FAILED, "源文件不存在"

    if _same_filesystem(src, dst_dir):
        return _move_same_fs(src, dst_dir)
    else:
        return _move_cross_fs(src, dst_dir)


def _rename_physical(src, new_main_name):
    if not os.path.exists(src):
        return RESULT_FAILED, "文件不存在"

    folder = os.path.dirname(src)
    old_name = os.path.basename(src)
    ext = os.path.splitext(old_name)[1]
    new_main_name = new_main_name.strip()

    if not new_main_name:
        return RESULT_FAILED, "文件名不能为空"

    target = os.path.join(folder, new_main_name + ext)
    if target == src:
        return RESULT_FAILED, "文件名未改变"

    try:
        target = _unique_target(folder, new_main_name + ext)
    except RuntimeError as e:
        return RESULT_FAILED, str(e)

    try:
        os.rename(src, target)
    except Exception as e:
        return RESULT_FAILED, str(e)

    return RESULT_SUCCESS, target


def _delete_physical(path):
    if not os.path.exists(path):
        return RESULT_FAILED, "文件不存在"

    try:
        from send2trash import send2trash
        send2trash(os.path.normpath(path))
        return RESULT_SUCCESS, None
    except Exception as e:
        return RESULT_FAILED, str(e)


def _to_db_path(real_path):
    library_root = database.get_library()
    if library_root:
        lib_norm = os.path.normcase(os.path.normpath(library_root))
        path_norm = os.path.normcase(os.path.normpath(real_path))
        if path_norm.startswith(lib_norm + os.sep):
            rel = os.path.relpath(real_path, library_root)
            return "managed", rel
    return "external", os.path.normpath(real_path)


def move_file(image_id, src_real_path, dst_dir):
    result, info = _move_physical(src_real_path, dst_dir)

    if result == RESULT_FAILED:
        return RESULT_FAILED, info

    if result == RESULT_PARTIAL:
        return RESULT_PARTIAL, info

    new_real_path = info
    new_storage_type, new_file_path = _to_db_path(new_real_path)

    if new_storage_type == "managed":
        rel_dir = os.path.dirname(new_file_path)
        if rel_dir:
            new_organize_status = "sorted"
        else:
            new_organize_status = "unsorted"
    else:
        new_organize_status = "unsorted"

    try:
        database.update_image_path(
            image_id=image_id,
            new_storage_type=new_storage_type,
            new_file_path=new_file_path,
            new_organize_status=new_organize_status,
            new_album_rel_path=None,
        )
    except Exception as e:
        return RESULT_FAILED, f"文件已移动，但数据库更新失败：{e}"

    return RESULT_SUCCESS, new_real_path


def move_files(image_id_path_pairs, dst_dir, src_album_for_undo=None,
               dst_album_for_undo=None):
    success = []
    partial = []
    failed = []
    moved_src = []
    moved_dst = []

    for image_id, src_real_path in image_id_path_pairs:
        result, info = move_file(image_id, src_real_path, dst_dir)
        if result == RESULT_SUCCESS:
            success.append((image_id, info))
            moved_src.append(src_real_path)
            moved_dst.append(info)
        elif result == RESULT_PARTIAL:
            partial.append((image_id, src_real_path, info))
        else:
            failed.append((image_id, src_real_path, info))

    if moved_src:
        try:
            database.record_operation(
                "move", moved_src, moved_dst,
                src_album_for_undo, dst_album_for_undo
            )
        except Exception:
            pass

    return success, partial, failed


def rename_file(image_id, src_real_path, new_main_name):
    result, info = _rename_physical(src_real_path, new_main_name)

    if result == RESULT_FAILED:
        return RESULT_FAILED, info

    new_real_path = info
    new_storage_type, new_file_path = _to_db_path(new_real_path)

    try:
        old_row = database.get_image_by_id(image_id)
        if old_row is None:
            return RESULT_FAILED, "图片记录不存在"

        database.update_image_path(
            image_id=image_id,
            new_storage_type=new_storage_type,
            new_file_path=new_file_path,
            new_organize_status=old_row["organize_status"],
            new_album_rel_path=old_row.get("album_rel_path"),
        )
    except Exception as e:
        return RESULT_FAILED, f"文件已重命名，但数据库更新失败：{e}"

    return RESULT_SUCCESS, new_real_path


def delete_file(image_id, real_path):
    result, err = _delete_physical(real_path)
    if result == RESULT_FAILED:
        return RESULT_FAILED, err

    try:
        database.delete_image_record(image_id)
    except Exception:
        pass

    return RESULT_SUCCESS, None


def delete_files(image_id_path_pairs):
    deleted = []
    failed = []

    for image_id, real_path in image_id_path_pairs:
        result, err = delete_file(image_id, real_path)
        if result == RESULT_SUCCESS:
            deleted.append((image_id, real_path))
        else:
            failed.append((image_id, real_path, err))

    return deleted, failed


def _move_to_exact_physical(src, dst_exact):
    if not os.path.exists(src):
        return RESULT_FAILED, "源文件不存在"

    if os.path.exists(dst_exact):
        return RESULT_FAILED, f"目标已存在：{dst_exact}"

    dst_dir = os.path.dirname(dst_exact)
    try:
        os.makedirs(dst_dir, exist_ok=True)
    except Exception as e:
        return RESULT_FAILED, f"无法创建目标目录：{e}"

    if _same_filesystem(src, dst_dir):
        try:
            os.rename(src, dst_exact)
        except Exception as e:
            return RESULT_FAILED, f"rename 失败：{e}"
        return RESULT_SUCCESS, dst_exact

    temp_path = _make_temp_path(dst_exact)

    try:
        shutil.copy2(src, temp_path)
    except Exception as e:
        _try_remove(temp_path)
        return RESULT_FAILED, f"复制失败：{e}"

    try:
        src_size = os.path.getsize(src)
        temp_size = os.path.getsize(temp_path)
    except OSError as e:
        _try_remove(temp_path)
        return RESULT_FAILED, f"无法读取文件大小：{e}"

    if src_size != temp_size:
        _try_remove(temp_path)
        return RESULT_FAILED, "复制不完整"

    try:
        os.rename(temp_path, dst_exact)
    except Exception as e:
        _try_remove(temp_path)
        return RESULT_FAILED, f"temp→final 失败：{e}"

    try:
        os.remove(src)
    except Exception as e:
        return RESULT_PARTIAL, (
            f"文件已到 {dst_exact}，但源删除失败：{e}"
        )

    return RESULT_SUCCESS, dst_exact


def move_to_exact_path(image_id, src_real_path, dst_real_path):
    result, info = _move_to_exact_physical(src_real_path, dst_real_path)

    if result == RESULT_FAILED:
        return RESULT_FAILED, info

    if result == RESULT_PARTIAL:
        return RESULT_PARTIAL, info

    new_real_path = info
    new_storage_type, new_file_path = _to_db_path(new_real_path)

    if new_storage_type == "managed":
        rel_dir = os.path.dirname(new_file_path)
        if rel_dir:
            new_organize_status = "sorted"
        else:
            new_organize_status = "unsorted"
    else:
        new_organize_status = "unsorted"

    try:
        database.update_image_path(
            image_id=image_id,
            new_storage_type=new_storage_type,
            new_file_path=new_file_path,
            new_organize_status=new_organize_status,
            new_album_rel_path=None,
        )
    except Exception as e:
        return RESULT_FAILED, f"文件已移动，但数据库更新失败：{e}"

    return RESULT_SUCCESS, new_real_path