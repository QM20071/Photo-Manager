"""
主题：颜色定义 + QSS 集中化。

- get_color(key)       取当前主题的颜色（QColor）
- get_color_str(key)   取当前主题的颜色（字符串，用于 QSS）
- apply_theme(app, theme)  把主题应用到 QApplication
- current_theme()      当前主题名

设计依据：
  《Phase 2B 设计 v2：UI 视觉系统规范》
"""

from PySide6.QtGui import QColor, QPalette
from PySide6.QtCore import Qt


# 主题版本（用于缓存 / 调试）
THEME_VERSION = 1


# 当前主题（模块级变量）
_current_theme = "light"


# ---------- 颜色定义 ----------

LIGHT = {
    # 背景
    "window_bg":       "#FAFAFA",
    "panel_bg":        "#FFFFFF",
    "sidebar_bg":      "#E0E0E0",
    "hover_bg":        "#F0F0F0",
    "selected_bg":     "#228B76",

    # 文字
    "text":            "#1A1A1A",
    "text_secondary":  "#6B6B6B",
    "selected_text":   "#1A1A1A",

    # 边框 / 分隔
    "border":          "#E5E5E5",
    "separator":       "#D0D0D0",
    "dock_sep":        "#C0C0C0",

    # 强调
    "accent":          "#4A90E2",
    "danger":          "#E53935",

    # 预览区背景（深浅都深）
    "preview_bg":      "#222222",
    "grid_bg":         "#FAFAFA",
}

DARK = {
    # 背景
    "window_bg":       "#1E1E1E",
    "panel_bg":        "#252526",
    "sidebar_bg":      "#1A1A1A",
    "hover_bg":        "#2D2D2D",
    "selected_bg":     "#2A4A6B",

    # 文字
    "text":            "#E0E0E0",
    "text_secondary":  "#A0A0A0",
    "selected_text":   "#FFFFFF",

    # 边框 / 分隔
    "border":          "#3C3C3C",
    "separator":       "#3A3A3A",
    "dock_sep":        "#000000",

    # 强调
    "accent":          "#5BA3F5",
    "danger":          "#FF6B6B",

    # 预览区背景
    "preview_bg":      "#1A1A1A",
    "grid_bg":         "#252526",
}


# ---------- 查询接口 ----------

def current_theme() -> str:
    return _current_theme


def _palette() -> dict:
    return DARK if _current_theme == "dark" else LIGHT


def get_color(key: str) -> QColor:
    """取当前主题的某个颜色，返回 QColor。"""
    return QColor(_palette().get(key, "#000000"))


def get_color_str(key: str) -> str:
    """取当前主题的某个颜色，返回字符串（用于 QSS）。"""
    return _palette().get(key, "#000000")


def get_all_colors() -> dict:
    """返回当前主题的所有颜色（用于 Delegate 缓存）。"""
    return dict(_palette())


# ---------- QSS 模板 ----------

QSS_TEMPLATE = """
/* ---------- 基础 ---------- */
QMainWindow, QDialog {{
    background-color: {window_bg};
}}
QWidget {{
    color: {text};
    font-size: 13px;
}}

/* ---------- 按钮 ---------- */
QPushButton {{
    background-color: {panel_bg};
    border: 1px solid {border};
    border-radius: 6px;
    padding: 4px 12px;
    color: {text};
    font-size: 13px;
    min-height: 20px;
}}
QPushButton:hover {{
    background-color: {hover_bg};
}}
QPushButton:pressed {{
    background-color: {selected_bg};
    color: #FFFFFF;
}}
QPushButton:disabled {{
    color: {text_secondary};
    background-color: {window_bg};
}}
QPushButton:checked {{
    background-color: {selected_bg};
    color: #FFFFFF;
}}
QPushButton[compact="true"] {{
    padding: 2px;
    font-size: 14px;
}}
QPushButton[menu="true"] {{
    padding-left: 20px;
    padding-right: 8px;
}}

/* ---------- Tab 按钮 ---------- */
QPushButton[tab="true"] {{
    border: none;
    border-radius: 6px;
    padding: 6px 16px;
    background-color: transparent;
    color: {text_secondary};
}}
QPushButton[tab="true"]:hover {{
    background-color: {hover_bg};
    color: {text};
}}
QPushButton[tab="true"]:checked {{
    background-color: {selected_bg};
    color: #FFFFFF;
    font-weight: 500;
}}

/* ---------- 输入框 ---------- */
QLineEdit {{
    background-color: {panel_bg};
    border: 1px solid {border};
    border-radius: 6px;
    padding: 0px 8px;
    color: {text};
    selection-background-color: {selected_bg};
    selection-color: {selected_text};
}}
QLineEdit:focus {{
    border-color: {accent};
}}

/* ---------- 下拉框 ---------- */
QComboBox {{
    background-color: {panel_bg};
    border: 1px solid {border};
    border-radius: 6px;
    padding: 4px 8px;
    color: {text};
    min-height: 20px;
}}
QComboBox:hover {{
    background-color: {hover_bg};
}}
QComboBox::drop-down {{
    border: none;
    width: 20px;
}}
QComboBox QAbstractItemView {{
    background-color: {panel_bg};
    border: 1px solid {border};
    border-radius: 6px;
    color: {text};
    selection-background-color: {selected_bg};
    selection-color: {selected_text};
    outline: none;
}}

/* ---------- 菜单 ---------- */
QMenu {{
    background-color: {panel_bg};
    border: 1px solid {border};
    border-radius: 6px;
    padding: 4px;
    color: {text};
}}
QMenu::item {{
    padding: 6px 24px 6px 12px;
    border-radius: 4px;
}}
QMenu::item:selected {{
    background-color: {selected_bg};
    color: {selected_text};
}}
QMenu::separator {{
    height: 1px;
    background-color: {border};
    margin: 4px 8px;
}}

/* ---------- 工具栏 ---------- */
QToolBar {{
    background-color: {window_bg};
    border: none;
    spacing: 6px;
    padding: 4px 8px;
}}
QToolBar::separator {{
    background-color: {separator};
    width: 1px;
    margin: 4px 6px;
}}

/* ---------- Dock 分隔条 ---------- */
QMainWindow::separator {{
    background-color: {dock_sep};
    width: 1px;
    height: 1px;
}}
QMainWindow::separator:hover {{
    background-color: {accent};
}}

/* ---------- 侧边栏 Dock ---------- */
QDockWidget#sidebar_left_dock,
QDockWidget#sidebar_right_dock {{
    background-color: {sidebar_bg};
    border: none;
}}
QDockWidget#sidebar_left_dock > QWidget,
QDockWidget#sidebar_right_dock > QWidget {{
    background-color: {sidebar_bg};
}}
QDockWidget#sidebar_left_dock::title,
QDockWidget#sidebar_right_dock::title {{
    background-color: {sidebar_bg};
    padding: 4px 6px;
    border-bottom: 1px solid {border};
}}

QWidget#SidebarLeft {{
    border-right: 1px solid {border};
}}
QWidget#InfoPanel {{
    border-left: 1px solid {border};
}}

/* ---------- 列表 / 网格 ---------- */
QListView {{
    background-color: {window_bg};
    border: none;
    outline: none;
}}

/* ---------- 滚动条 ---------- */
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {border};
    border-radius: 5px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: {text_secondary};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: {border};
    border-radius: 5px;
    min-width: 30px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {text_secondary};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: transparent;
}}

/* ---------- 进度条 ---------- */
QProgressBar {{
    background-color: {window_bg};
    border: 1px solid {border};
    border-radius: 4px;
    text-align: center;
    color: {text};
    height: 16px;
}}
QProgressBar::chunk {{
    background-color: {accent};
    border-radius: 3px;
}}

/* ---------- 文本编辑 ---------- */
QTextEdit {{
    background-color: {panel_bg};
    border: 1px solid {border};
    border-radius: 6px;
    padding: 4px 8px;
    color: {text};
    selection-background-color: {selected_bg};
    selection-color: {selected_text};
}}

/* ---------- 提示 ---------- */
QToolTip {{
    background-color: {panel_bg};
    border: 1px solid {border};
    border-radius: 6px;
    padding: 4px 8px;
    color: {text};
}}

/* ---------- 标签 ---------- */
QLabel {{
    background: transparent;
    color: {text};
}}

/* ---------- 滚动区域 ---------- */
QScrollArea {{
    background-color: {window_bg};
    border: none;
}}
"""

# ---------- 应用主题 ----------

def apply_theme(app, theme: str):
    """
    把主题应用到 QApplication。
      - 设置 Fusion 风格
      - 设置 palette
      - 设置 QSS
    """
def apply_theme(app, theme: str):
    """
    把主题应用到 QApplication。
      - 设置 Fusion 风格
      - 设置 palette
      - 设置 QSS
    """
    if theme not in ("light", "dark"):
        theme = "light"

    global _current_theme
    _current_theme = theme

    app.setStyle("Fusion")

    palette = DARK if theme == "dark" else LIGHT

    qp = QPalette()
    qp.setColor(QPalette.Window, QColor(palette["window_bg"]))
    qp.setColor(QPalette.WindowText, QColor(palette["text"]))
    qp.setColor(QPalette.Base, QColor(palette["panel_bg"]))
    qp.setColor(QPalette.AlternateBase, QColor(palette["window_bg"]))
    qp.setColor(QPalette.Text, QColor(palette["text"]))
    qp.setColor(QPalette.Button, QColor(palette["panel_bg"]))
    qp.setColor(QPalette.ButtonText, QColor(palette["text"]))
    qp.setColor(QPalette.Highlight, QColor(palette["selected_bg"]))
    qp.setColor(QPalette.HighlightedText, QColor(palette["selected_text"]))
    qp.setColor(QPalette.ToolTipBase, QColor(palette["panel_bg"]))
    qp.setColor(QPalette.ToolTipText, QColor(palette["text"]))
    qp.setColor(QPalette.PlaceholderText, QColor(palette["text_secondary"]))
    app.setPalette(qp)

    qss = QSS_TEMPLATE.format(**palette)
    app.setStyleSheet(qss)