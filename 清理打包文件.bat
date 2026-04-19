@echo off
chcp 65001 >nul
title 清理打包文件

set "APP_EXE=WindowPilot.exe"
set "LEGACY_EXE=GameAssistant.exe"

echo ========================================
echo    清理打包临时文件
echo ========================================
echo.

REM 检查是否以管理员身份运行
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [警告] 建议以管理员身份运行以获得完全权限
    echo.
)

REM 结束可能在运行的进程
echo [1/4] 检查并结束相关进程...
taskkill /F /IM %APP_EXE% >NUL 2>&1
taskkill /F /IM %LEGACY_EXE% >NUL 2>&1
timeout /t 1 >NUL
echo       已尝试结束 %APP_EXE% 和旧版 %LEGACY_EXE%
echo.

REM 清理 build 文件夹
echo [2/4] 清理 build 文件夹...
if exist "build\" (
    rmdir /s /q build 2>NUL
    if exist "build\" (
        echo       第一次尝试失败，等待后重试...
        timeout /t 2 >NUL
        rd /s /q build 2>NUL
    )
    if exist "build\" (
        echo       [失败] 无法删除 build 文件夹
        echo       请手动删除该文件夹
    ) else (
        echo       [成功] build 文件夹已删除
    )
) else (
    echo       build 文件夹不存在
)
echo.

REM 清理 dist 文件夹
echo [3/4] 清理 dist 文件夹...
if exist "dist\" (
    rmdir /s /q dist 2>NUL
    if exist "dist\" (
        echo       第一次尝试失败，等待后重试...
        timeout /t 2 >NUL
        rd /s /q dist 2>NUL
    )
    if exist "dist\" (
        echo       [失败] 无法删除 dist 文件夹
        echo       请手动删除该文件夹
    ) else (
        echo       [成功] dist 文件夹已删除
    )
) else (
    echo       dist 文件夹不存在
)
echo.

REM 清理 spec 文件
echo [4/4] 清理 .spec 文件...
if exist "*.spec" (
    del /q *.spec 2>NUL
    if exist "*.spec" (
        echo       [失败] 无法删除 .spec 文件
    ) else (
        echo       [成功] .spec 文件已删除
    )
) else (
    echo       没有 .spec 文件
)
echo.

REM 清理 __pycache__
echo [额外] 清理 __pycache__ 文件夹...
for /d /r %%i in (__pycache__) do (
    if exist "%%i" (
        rmdir /s /q "%%i" 2>NUL
    )
)
echo       [完成] __pycache__ 清理完成
echo.

echo ========================================
echo [完成] 清理操作完成
echo ========================================
echo.
echo 现在可以重新尝试打包了
echo.
pause
