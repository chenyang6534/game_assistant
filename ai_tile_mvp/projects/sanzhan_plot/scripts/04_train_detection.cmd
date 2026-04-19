@echo off
setlocal
set PROJECT_ROOT=%~dp0..
set AI_ROOT=%PROJECT_ROOT%\..\..

python "%AI_ROOT%\scripts\train_yolo_tile.py" --data "%PROJECT_ROOT%\datasets\detection\data.yaml" --model yolov8n.pt --epochs 120 --imgsz 640 --project "%PROJECT_ROOT%\outputs\train" --name "sanzhan_plot_det_yolov8n"
set EXIT_CODE=%ERRORLEVEL%
echo.
if not "%EXIT_CODE%"=="0" (
  echo 命令执行失败，退出码 %EXIT_CODE%。
) else (
  echo 命令执行完成。
)
pause
exit /b %EXIT_CODE%
