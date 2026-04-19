@echo off
setlocal
set PROJECT_ROOT=%~dp0..
set AI_ROOT=%PROJECT_ROOT%\..\..

python "%AI_ROOT%\scripts\split_yolo_dataset.py" --source-images "%PROJECT_ROOT%\datasets\detection\raw\images" --source-labels "%PROJECT_ROOT%\datasets\detection\raw\labels" --output-root "%PROJECT_ROOT%\datasets\detection" --clear-output
set EXIT_CODE=%ERRORLEVEL%
echo.
if not "%EXIT_CODE%"=="0" (
  echo 命令执行失败，退出码 %EXIT_CODE%。
) else (
  echo 命令执行完成。
)
pause
exit /b %EXIT_CODE%
