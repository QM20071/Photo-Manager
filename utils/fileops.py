"""
文件操作相关的工具函数。

- reveal_in_explorer(path)       在资源管理器中定位文件
- open_folder_in_explorer(folder) 打开文件夹
- safe_move(src, dst_dir)         移动文件（重名加后缀）
- rename_in_place(src, new_name)  原地重命名（保持扩展名）

注：
  真正"移动 / 重命名 / 删除"的统一入口在 file_manager.py。
  本模块只提供"纯物理操作"和"打开资源管理器"等辅助函数。
"""

import os
import shutil
import subprocess


def reveal_in_explorer(path):
    """在资源管理器中定位文件。"""
    if not os.path.exists(path):
        return False
    try:
        subprocess.run(["explorer", "/select,", os.path.normpath(path)])
        return True
    except Exception:
        return False


def open_folder_in_explorer(folder):
    """打开文件夹。"""
    if not os.path.isdir(folder):
        return False
    try:
        subprocess.run(["explorer", os.path.normpath(folder)])
        return True
    except Exception:
        return False


def safe_move(src, dst_dir):
    """
    把文件移动到目标目录，重名时自动加 (n)。
    返回 (成功, 新路径 或 错误信息)。
    """
    if not os.path.exists(src):
        return False, "源文件不存在"

    os.makedirs(dst_dir, exist_ok=True)
    base = os.path.basename(src)
    name, ext = os.path.splitext(base)
    target = os.path.join(dst_dir, base)

    counter = 1
    while os.path.exists(target):
        target = os.path.join(dst_dir, f"{name}({counter}){ext}")
        counter += 1
        if counter > 1000:
            return False, "重名过多"

    try:
        shutil.move(src, target)
        return True, target
    except Exception as e:
        return False, str(e)


def rename_in_place(src, new_main_name):
    """
    原地重命名（保持扩展名）。返回 (成功, 新路径 或 错误信息)。
    """
    if not os.path.exists(src):
        return False, "文件不存在"

    folder = os.path.dirname(src)
    old_name = os.path.basename(src)
    ext = os.path.splitext(old_name)[1]
    new_main_name = new_main_name.strip()

    if not new_main_name:
        return False, "文件名不能为空"

    target = os.path.join(folder, new_main_name + ext)
    if target == src:
        return False, "文件名未改变"

    counter = 1
    while os.path.exists(target):
        target = os.path.join(folder, f"{new_main_name}({counter}){ext}")
        counter += 1
        if counter > 1000:
            return False, "重名过多"

    try:
        os.rename(src, target)
        return True, target
    except Exception as e:
        return False, str(e)