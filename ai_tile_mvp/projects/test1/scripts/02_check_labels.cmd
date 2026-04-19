@echo off
setlocal
set PROJECT_ROOT=%~dp0..
set AI_ROOT=%PROJECT_ROOT%\..\..

python "%AI_ROOT%\scripts\check_yolo_labels.py" --image-dir "%PROJECT_ROOT%\datasets\detection\raw\images" --label-dir "%PROJECT_ROOT%\datasets\detection\raw\labels" --output-dir "%PROJECT_ROOT%\outputs\label_check" --sample-count 40
set EXIT_CODE=%ERRORLEVEL%
echo.
if not "%EXIT_CODE%"=="0" (
  echo 命令执行失败，退出码 %EXIT_CODE%。
) else (
  echo 命令执行完成。
)
pause
exit /b %EXIT_CODE%
