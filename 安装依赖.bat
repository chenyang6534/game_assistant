@echo off
chcp 65001 >nul
title 安装依赖库

echo ========================================
echo    安装 Game Assistant 依赖库
echo ========================================
echo.

REM 检查Python
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

echo [信息] Python版本:
python --version
echo.

REM 升级pip
echo [1/2] 正在升级pip...
python -m pip install --upgrade pip
echo.

REM 安装依赖
echo [2/2] 正在安装依赖库...
echo.
pip install -r requirements.txt

if %errorLevel% neq 0 (
    echo.
    echo [错误] 安装失败！
    echo.
    echo 可能的原因:
    echo 1. 网络连接问题
    echo 2. 需要管理员权限
    echo 3. pip配置问题
    echo.
    echo 建议:
    echo 1. 使用管理员身份运行此脚本
    echo 2. 检查网络连接
    echo 3. 尝试使用国内镜像源:
    echo    pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
    echo.
    pause
    exit /b 1
)

echo.
echo ========================================
echo [成功] 所有依赖库安装完成！
echo ========================================
echo.
echo 你现在可以运行程序了:
echo 方式1: 双击 "快速启动.bat"
echo 方式2: 以管理员身份运行命令: python main.py
echo.
pause
