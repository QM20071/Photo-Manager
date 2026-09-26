"""
统一的图片读取初始化。

所有需要打开图片的模块（main / viewer / metadata / migrate / ...）
都应该在启动早期调用 init_image_readers()，而不是各自注册一次。

当前负责：
  - 注册 pillow-heif，使 Pillow 能打开 HEIF / HEIC
"""

import pillow_heif


_initialized = False


def init_image_readers():
    """
    初始化图片读取支持。幂等：多次调用只注册一次。
    """
    global _initialized
    if _initialized:
        return
    pillow_heif.register_heif_opener()
    _initialized = True