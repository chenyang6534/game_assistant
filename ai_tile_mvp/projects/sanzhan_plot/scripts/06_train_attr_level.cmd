@echo off
setlocal
set PROJECT_ROOT=%~dp0..
set AI_ROOT=%PROJECT_ROOT%\..\..

python "%AI_ROOT%\scripts\train_yolo_attribute_cls.py" --data-root "%PROJECT_ROOT%\datasets\attribute_cls\level" --model yolov8n-cls.pt --epochs 80 --imgsz 224 --project "%PROJECT_ROOT%\outputs\train_attr" --name "level_yolov8n_cls"
set EXIT_CODE=%ERRORLEVEL%
echo.
if not "%EXIT_CODE%"=="0" (
  echo 命令执行失败，退出码 %EXIT_CODE%。
) else (
  echo 命令执行完成。
)
pause
exit /b %EXIT_CODE%
