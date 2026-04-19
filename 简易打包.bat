@echo off
REM Simple Packaging Script - Run as NORMAL user (NOT administrator)
title PyInstaller - Game Assistant

REM Switch to script directory
cd /d "%~dp0"

echo ========================================
echo    Game Assistant Packaging Tool
echo ========================================
echo.
echo Current directory: %CD%
echo.

REM Check if running from system32 (wrong location)
echo %CD% | findstr /I "system32" >nul
if %errorlevel% equ 0 (
    echo [ERROR] Do NOT run from System32!
    echo [TIP] Right-click this file -^> Edit, copy content,
    echo       then create new .bat file in game_assistant folder
    echo.
    pause
    exit /b 1
)

REM Check Python
python --version >nul 2>&1
if %errorLevel% neq 0 (
    echo [ERROR] Python not found!
    echo Please install Python 3.9+ from python.org
    pause
    exit /b 1
)

echo Python version:
python --version
echo.

REM Check PyInstaller
python -c "import PyInstaller" >nul 2>&1
if %errorLevel% neq 0 (
    echo Installing PyInstaller...
    pip install pyinstaller
)

REM Kill running process
taskkill /F /IM GameAssistant.exe >NUL 2>&1

REM Clean old files
if exist "build" rmdir /s /q build 2>nul
if exist "dist" rmdir /s /q dist 2>nul
del /q *.spec 2>nul

echo.
echo Starting packaging (5-10 minutes)...
echo.

REM Package
python -m PyInstaller ^
    --name=GameAssistant ^
    --windowed ^
    --onedir ^
    --noconfirm ^
    --hidden-import=win32gui ^
    --hidden-import=win32api ^
    --hidden-import=win32con ^
    --hidden-import=pywintypes ^
    --hidden-import=win32clipboard ^
    --hidden-import=pynput.keyboard._win32 ^
    --hidden-import=pynput.mouse._win32 ^
    --collect-all=PySide6 ^
    --collect-all=rapidocr_onnxruntime ^
    main.py

if %errorLevel% neq 0 (
    echo.
    echo [ERROR] Packaging failed!
    echo.
    echo Common solutions:
    echo 1. Run as NORMAL user, NOT administrator
    echo 2. Make sure you are in game_assistant folder
    echo 3. Close all antivirus software
    echo 4. Delete build and dist folders manually
    echo.
    pause
    exit /b 1
)

echo.
echo ========================================
echo [SUCCESS] Done!
echo ========================================
echo.
echo Output: dist\GameAssistant\GameAssistant.exe
echo.

explorer dist\GameAssistant
pause
