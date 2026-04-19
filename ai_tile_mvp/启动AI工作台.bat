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

echo 启动 AI 地块识别工作台...
"%PYTHON_EXE%" workbench.py

if errorlevel 1 (
    echo.
    echo 工作台执行失败，请检查 Python 环境和依赖。
)

pause