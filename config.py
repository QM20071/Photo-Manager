"""
配置文件读写。

配置文件：程序目录下的 config.json
"""

import json
import os
import sys


def _app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


CONFIG_PATH = os.path.join(_app_dir(), "config.json")


def load_config():
    if not os.path.exists(CONFIG_PATH):
        return {}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def get_library_path():
    return load_config().get("library_path")


def set_library_path(path):
    cfg = load_config()
    cfg["library_path"] = path
    save_config(cfg)


def get_delete_warned():
    return load_config().get("delete_warned", False)


def set_delete_warned():
    cfg = load_config()
    cfg["delete_warned"] = True
    save_config(cfg)


def get_theme():
    t = load_config().get("theme", "light")
    if t not in ("light", "dark"):
        t = "light"
    return t


def set_theme(theme):
    cfg = load_config()
    cfg["theme"] = theme
    save_config(cfg)


def is_safe_mode():
    return load_config().get("safe_mode", False)


def set_safe_mode(on=True):
    cfg = load_config()
    cfg["safe_mode"] = bool(on)
    save_config(cfg)


def get_running_flag():
    return load_config().get("running", False)


def set_running_flag(on=True):
    cfg = load_config()
    cfg["running"] = bool(on)
    save_config(cfg)

def cleanup_legacy_keys():
    cfg = load_config()
    if "scan_paths" in cfg:
        cfg.pop("scan_paths", None)
        save_config(cfg)
        return True
    return False