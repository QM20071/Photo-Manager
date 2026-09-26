"""
排序相关工具。

- sort_paths(paths, mode)        按模式排序图片路径列表
- sort_albums(albums, mode, lib) 按模式排序相册名列表
"""

import os


def sort_paths(paths, mode):
    """按指定模式排序图片路径列表。"""
    try:
        if mode == "added_asc":
            return list(paths)
        elif mode == "added_desc":
            return list(reversed(paths))
        elif mode == "name_asc":
            return sorted(paths, key=lambda p: os.path.basename(p).lower())
        elif mode == "name_desc":
            return sorted(paths, key=lambda p: os.path.basename(p).lower(),
                          reverse=True)
        elif mode == "mtime_asc":
            def _mt(p):
                try:
                    return os.path.getmtime(p)
                except OSError:
                    return 0
            return sorted(paths, key=_mt)
        elif mode == "mtime_desc":
            def _mt(p):
                try:
                    return os.path.getmtime(p)
                except OSError:
                    return 0
            return sorted(paths, key=_mt, reverse=True)
        elif mode == "size_asc":
            def _sz(p):
                try:
                    return os.path.getsize(p)
                except OSError:
                    return 0
            return sorted(paths, key=_sz)
        elif mode == "size_desc":
            def _sz(p):
                try:
                    return os.path.getsize(p)
                except OSError:
                    return 0
            return sorted(paths, key=_sz, reverse=True)
    except Exception:
        pass
    return list(paths)


def sort_albums(albums, mode, lib):
    """按指定模式排序相册名列表。"""
    try:
        if mode == "name_asc":
            return sorted(albums, key=lambda x: x.lower())
        elif mode == "name_desc":
            return sorted(albums, key=lambda x: x.lower(), reverse=True)
        elif mode == "mtime_asc":
            def _mt(name):
                try:
                    return os.path.getmtime(os.path.join(lib, name))
                except OSError:
                    return 0
            return sorted(albums, key=_mt)
        elif mode == "mtime_desc":
            def _mt(name):
                try:
                    return os.path.getmtime(os.path.join(lib, name))
                except OSError:
                    return 0
            return sorted(albums, key=_mt, reverse=True)
    except Exception:
        pass
    return sorted(albums, key=lambda x: x.lower())