"""
图片元信息：尺寸、大小、时间、EXIF、后台读取月份。

- get_image_info(path)          单张图 (尺寸字符串, 字节数)
- get_album_info(album_name)    相册内 (图片数, 总字节数)
- format_size(n)                字节数格式化成人类可读
- format_time(t)                时间戳格式化
- get_exif_info(path)           读取 EXIF 关键字段
- MonthLoader                   后台线程：批量读取一批图片的月份
"""

import os
import time

from PySide6.QtCore import QThread, Signal
from PIL import Image, ExifTags

import database


from core.scanner import IMAGE_EXTS


def get_image_info(path):
    """返回 (尺寸字符串, 字节数)；读取失败时 (None, 0)。"""
    try:
        size_bytes = os.path.getsize(path)
        with Image.open(path) as img:
            w, h = img.size
        return f"{w} × {h}", size_bytes
    except Exception:
        return None, 0


def get_album_info(album_name):
    """返回相册内 (图片数量, 总字节数)。"""
    lib = database.get_library()
    folder = os.path.join(lib, album_name)
    if not os.path.isdir(folder):
        return 0, 0

    count = 0
    total = 0
    for root, _, files in os.walk(folder):
        for f in files:
            if os.path.splitext(f)[1].lower() in IMAGE_EXTS:
                count += 1
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
    return count, total


def format_size(n):
    if n < 1024:
        return f"{n} B"
    elif n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    elif n < 1024 * 1024 * 1024:
        return f"{n / 1024 / 1024:.1f} MB"
    else:
        return f"{n / 1024 / 1024 / 1024:.2f} GB"


def format_time(t):
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(t))
    except Exception:
        return ""


def get_exif_info(path):
    """读取 EXIF 关键字段，返回 {中文标签: 值}。失败返回空 dict。"""
    result = {}
    try:
        with Image.open(path) as img:
            exif = img.getexif()
            if not exif:
                return result

            tag_map = {ExifTags.TAGS.get(k, k): v for k, v in exif.items()}

            field_map = {
                "Make": "相机厂商",
                "Model": "相机型号",
                "DateTime": "拍摄时间",
                "DateTimeOriginal": "原始拍摄时间",
                "LensModel": "镜头",
                "Software": "软件",
            }

            for tag, label in field_map.items():
                v = tag_map.get(tag)
                if v:
                    result[label] = str(v).strip()

            # 曝光相关（在 Exif 子 IFD 里）
            try:
                ifd = exif.get_ifd(ExifTags.IFD.Exif)
                if ifd:
                    ifd_map = {ExifTags.TAGS.get(k, k): v
                               for k, v in ifd.items()}
                    fnumber = ifd_map.get("FNumber")
                    exposure = ifd_map.get("ExposureTime")
                    iso = (ifd_map.get("ISOSpeedRatings")
                           or ifd_map.get("PhotographicSensitivity"))
                    focal = ifd_map.get("FocalLength")

                    if fnumber:
                        try:
                            result["光圈"] = f"f/{float(fnumber):.1f}"
                        except Exception:
                            result["光圈"] = str(fnumber)
                    if exposure:
                        try:
                            num = float(exposure)
                            if num < 1:
                                result["快门"] = f"1/{int(1 / num)}"
                            else:
                                result["快门"] = f"{num}s"
                        except Exception:
                            result["快门"] = str(exposure)
                    if iso:
                        if isinstance(iso, (list, tuple)):
                            iso = iso[0]
                        result["ISO"] = str(iso)
                    if focal:
                        try:
                            result["焦距"] = f"{float(focal):.0f}mm"
                        except Exception:
                            result["焦距"] = str(focal)
            except Exception:
                pass

            # GPS
            try:
                gps_ifd = exif.get_ifd(ExifTags.IFD.GPSInfo)
                if gps_ifd:
                    gps_map = {ExifTags.GPSTAGS.get(k, k): v
                               for k, v in gps_ifd.items()}
                    lat = gps_map.get("GPSLatitude")
                    lat_ref = gps_map.get("GPSLatitudeRef", "")
                    lon = gps_map.get("GPSLongitude")
                    lon_ref = gps_map.get("GPSLongitudeRef", "")

                    def to_deg(val):
                        try:
                            d = float(val[0])
                            m = float(val[1])
                            s = float(val[2])
                            return d + m / 60 + s / 3600
                        except Exception:
                            return None

                    if lat and lon:
                        la = to_deg(lat)
                        lo = to_deg(lon)
                        if la is not None and lo is not None:
                            if lat_ref == "S":
                                la = -la
                            if lon_ref == "W":
                                lo = -lo
                            result["GPS"] = f"{la:.6f}, {lo:.6f}"
            except Exception:
                pass

    except Exception:
        pass
    return result


class MonthLoader(QThread):
    """
    后台线程：批量读取一批图片的月份。

    信号：
      month_ready(list)  [(path, "YYYY-MM"), ...]
      finished_all()
    """

    month_ready = Signal(list)
    finished_all = Signal()

    BATCH = 20

    def __init__(self, paths):
        super().__init__()
        self.paths = paths
        self._stop = False

    def run(self):
        batch = []
        for p in self.paths:
            if self._stop:
                break

            month = "未知"
            # 优先 EXIF 拍摄时间
            try:
                with Image.open(p) as img:
                    exif = img.getexif()
                    if exif:
                        tag_map = {ExifTags.TAGS.get(k, k): v
                                   for k, v in exif.items()}
                        dt = (tag_map.get("DateTimeOriginal")
                              or tag_map.get("DateTime"))
                        if dt:
                            s = str(dt).strip()
                            if len(s) >= 7:
                                month = s[:7].replace(":", "-")
            except Exception:
                pass

            # 退回文件修改时间
            if month == "未知":
                try:
                    t = os.path.getmtime(p)
                    month = time.strftime("%Y-%m", time.localtime(t))
                except Exception:
                    pass

            batch.append((p, month))
            if len(batch) >= self.BATCH:
                self.month_ready.emit(batch)
                batch = []

        if batch:
            self.month_ready.emit(batch)

        self.finished_all.emit()

    def stop(self):
        self._stop = True