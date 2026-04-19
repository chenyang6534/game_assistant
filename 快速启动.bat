@echo off
chcp 65001 >nul
title Game Assistant - 游戏辅助工具

echo ========================================
echo    Game Assistant - 游戏辅助工具
echo ========================================
echo.

REM 检查是否以管理员身份运行
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [警告] 未以管理员权限运行
    echo 某些功能可能无法正常工作
    echo.
    echo 建议：右键此文件 -^> 以管理员身份运行
    echo.
    pause
)

REM 检查Python是否安装
python --version >nul 2>&1
if %errorLevel% neq 0 (
    echo [错误] 未检测到Python！
    echo.
    echo 请先安装Python 3.9或更高版本
    echo 下载地址: https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

echo [信息] Python环境检测成功
echo.

REM 检查依赖
echo [信息] 正在检查依赖库...
python -c "import mss, cv2, numpy, pynput, keyboard, PySide6" >nul 2>&1
if %errorLevel% neq 0 (
    echo [警告] 检测到缺失依赖库
    echo.
    echo 是否自动安装？(Y/N)
    choice /C YN /N /M "请选择: "
    if errorlevel 2 (
        echo 已取消安装
        pause
        exit /b 1
    )
    
    echo.
    echo [信息] 正在安装依赖库，请稍候...
    python -m pip install --upgrade pip
    pip install -r requirements.txt
    
    if %errorLevel% neq 0 (
        echo.
        echo [错误] 依赖安装失败！
        echo 请检查网络连接或手动运行: pip install -r requirements.txt
        pause
        exit /b 1
    )
    
    echo.
    echo [成功] 依赖安装完成！
)

echo [信息] 依赖检查完成
echo.

REM 启动程序
echo [信息] 正在启动程序...
echo.
python main.py

if %errorLevel% neq 0 (
    echo.
    echo [错误] 程序运行出错！
    pause
)
