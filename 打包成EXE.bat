@echo off
REM 设置代码页为 UTF-8
chcp 65001 >nul 2>nul
title 打包 WindowPilot 为 EXE

set "APP_NAME=WindowPilot"
set "APP_EXE=%APP_NAME%.exe"
set "DIST_DIR=%APP_NAME%"
set "LEGACY_EXE=GameAssistant.exe"

echo ========================================
echo    打包 WindowPilot 为 EXE
echo ========================================
echo.

REM 切换到脚本所在目录
cd /d "%~dp0"
echo [信息] 当前目录: %CD%
echo.

REM 检查是否以管理员身份运行（不推荐）
net session >nul 2>&1
if %errorLevel% equ 0 (
    echo [警告] 检测到以管理员身份运行
    echo [提示] PyInstaller 不需要管理员权限，建议以普通用户运行
    echo.
)

REM 检查Python
python --version >nul 2>&1
if %errorLevel% neq 0 (
    echo [ERROR] Python not detected!
    pause
    exit /b 1
)

echo [INFO] Checking PyInstaller...
python -c "import PyInstaller" >nul 2>&1
if %errorLevel% neq 0 (
    echo [INFO] Installing PyInstaller...
    pip install pyinstaller
    if %errorLevel% neq 0 (
        echo [ERROR] PyInstaller installation failed!
        pause
        exit /b 1
    )
)

echo [INFO] PyInstaller ready
echo.

REM 检查并结束可能在运行的进程
echo [INFO] Checking for running processes...
taskkill /F /IM %APP_EXE% >NUL 2>&1
taskkill /F /IM %LEGACY_EXE% >NUL 2>&1

REM 清理旧文件
if exist "build\" (
    echo [INFO] Cleaning old build folder...
    timeout /t 1 >NUL
    rmdir /s /q build 2>NUL
    if exist "build\" (
        echo [WARN] Cannot delete build folder, trying force delete...
        rd /s /q build 2>NUL
    )
)
if exist "dist\" (
    echo [INFO] Cleaning old dist folder...
    timeout /t 1 >NUL
    rmdir /s /q dist 2>NUL
    if exist "dist\" (
        echo [WARN] Cannot delete dist folder, trying force delete...
        rd /s /q dist 2>NUL
        timeout /t 2 >NUL
    )
)
if exist "*.spec" (
    echo [INFO] Cleaning old .spec files...
    del /q *.spec 2>NUL
)

echo.
echo [INFO] Starting packaging...
echo [TIP] This may take 5-10 minutes, please wait...
echo.

REM 打包命令
pyinstaller --name="%APP_NAME%" ^
    --windowed ^
    --onedir ^
    --add-data="templates;templates" ^
    --add-data="config.json;." ^
    --hidden-import=win32gui ^
    --hidden-import=win32api ^
    --hidden-import=win32con ^
    --hidden-import=pywintypes ^
    --hidden-import=win32clipboard ^
    --hidden-import=pynput.keyboard._win32 ^
    --hidden-import=pynput.mouse._win32 ^
    --collect-all=PySide6 ^
    --collect-all=rapidocr_onnxruntime ^
    --noconfirm ^
    main.py

if %errorLevel% neq 0 (
    echo.
    echo ========================================
    echo [ERROR] Packaging failed!
    echo ========================================
    echo.
    echo Possible reasons and solutions:
    echo.
    echo 1. Permission issue
    echo    Solution: Run as NORMAL user (NOT administrator^)
    echo.
    echo 2. Program is running
    echo    Solution: Close all WindowPilot.exe processes
    echo.
    echo 3. Antivirus interference
    echo    Solution: Disable antivirus or add folder to whitelist
    echo.
    echo 4. File is locked
    echo    Solution: Manually delete dist and build folders
    echo.
    echo 5. Insufficient disk space
    echo    Solution: Ensure at least 2GB free space
    echo.
    echo 6. Running from wrong directory
    echo    Solution: Navigate to project folder first
    echo.
    pause
    exit /b 1
)

echo.
echo ========================================
echo [SUCCESS] Packaging completed!
echo ========================================
echo.
echo Executable location: dist\%DIST_DIR%\%APP_EXE%
echo.
echo Distribution instructions:
echo 1. Copy the entire dist\%DIST_DIR% folder to target PC
echo 2. Right-click %APP_EXE% -^> Run as administrator
echo.
echo Open output folder now? (Y/N^)
choice /C YN /N /M "Choose: "
if errorlevel 1 if not errorlevel 2 (
    explorer dist\%DIST_DIR%
)

pause
