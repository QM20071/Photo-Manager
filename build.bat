@echo off
chcp 65001 >nul
echo ========================================
echo   Photo Manager - Nuitka Build
echo ========================================
echo.

cd /d "%~dp0"

echo [1/4] Cleaning...
if exist dist_nuitka rmdir /s /q dist_nuitka

echo [2/4] Activating venv...
call pack_env\Scripts\activate

echo [3/4] Checking Nuitka...
python -m nuitka --version >nul 2>&1
if errorlevel 1 (
    echo Installing Nuitka...
    pip install nuitka -i https://pypi.tuna.tsinghua.edu.cn/simple
)

echo [4/4] Building...
python -m nuitka ^
    --standalone ^
    --enable-plugin=pyside6 ^
    --include-package=core ^
    --include-package=ui ^
    --include-package=utils ^
    --include-module=pillow_heif ^
    --include-data-dir=resources=resources ^
    --windows-icon-from-ico=resources/app.ico ^
    --output-dir=dist_nuitka ^
    main.py

echo.
echo ========================================
echo   Build complete!
echo   dist_nuitka\main.dist\
echo ========================================
pause