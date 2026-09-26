@echo off
chcp 65001 >nul
echo ========================================
echo   图片管理器 - Nuitka 打包（测试版）
echo ========================================
echo.

cd /d "%~dp0"

echo [1/3] 清理旧的编译产物...
if exist dist_nuitka rmdir /s /q dist_nuitka

echo [2/3] 激活虚拟环境...
call pack_env\Scripts\activate

echo [3/3] 开始编译（可能几分钟）...
python -m nuitka ^
    --standalone ^
    --enable-plugin=pyside6 ^
    --include-package=core ^
    --include-package=ui ^
    --include-package=utils ^
    --include-module=pillow_heif ^
    --output-dir=dist_nuitka ^
    main.py

echo.
echo ========================================
echo   打包完成！
echo   dist_nuitka\main.dist\
echo ========================================
pause