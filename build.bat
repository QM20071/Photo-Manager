@echo off
chcp 65001 >nul
echo ========================================
echo   图片管理器 - Nuitka 打包
echo ========================================
echo.

cd /d "%~dp0"

echo [1/4] 清理旧的编译产物...
if exist dist_nuitka rmdir /s /q dist_nuitka

echo [2/4] 激活虚拟环境...
call pack_env\Scripts\activate

echo [3/4] 确认 Nuitka 已装...
python -m nuitka --version >nul 2>&1
if errorlevel 1 (
    echo Nuitka 未安装，正在安装...
    pip install nuitka -i https://pypi.tuna.tsinghua.edu.cn/simple
)

echo [4/4] 开始编译（可能几分钟）...
python -m nuitka ^
    --standalone ^
    --enable-plugin=pyside6 ^
    --include-package=core ^
    --include-package=ui ^
    --include-package=utils ^
    --include-module=pillow_heif ^
    --include-data-dir=resources=resources ^
    --output-dir=dist_nuitka ^
    main.py

echo.
echo ========================================
echo   打包完成！
echo   dist_nuitka\main.dist\
echo ========================================
pause