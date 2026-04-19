@echo off
setlocal
cd /d %~dp0

if exist "%~dp0..\..\.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%~dp0..\..\.venv\Scripts\python.exe"
) else if exist "%~dp0..\.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%~dp0..\.venv\Scripts\python.exe"
) else (
    set "PYTHON_EXE=python"
)

echo 启动 AI 地块采样向导...
"%PYTHON_EXE%" scripts\sample_map_tiles_interactive.py

if errorlevel 1 (
    echo.
    echo 采样脚本执行失败，请检查 Python 环境和依赖。
)

pause