# 图片管理器

一个简洁、离线、Windows 上运行的个人图片管理器。

## 功能

- 图库管理（导入、扫描、整理）
- 缩略图浏览（可见区域驱动）
- 相册（真实文件夹）
- 搜索（文件名 + 拼音首字母）
- 排序、月份筛选、收藏
- 拖拽整理
- 浅色 / 深色主题
- EXIF 查看

## 技术栈

- Python 3.10
- PySide6
- Pillow + pillow-heif
- SQLite
- Nuitka（打包）

## 运行
pip install PySide6 Pillow pillow-heif send2trash
python main.py

text

## 打包
build.bat