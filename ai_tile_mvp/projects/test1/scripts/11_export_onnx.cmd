@echo off
setlocal
set PROJECT_ROOT=%~dp0..
set AI_ROOT=%PROJECT_ROOT%\..\..

python "%AI_ROOT%\scripts\export_yolo_onnx.py" --weights "%PROJECT_ROOT%\outputs\train\test1_det_yolov8n\weights\best.pt" --output "%PROJECT_ROOT%\models\detector\test1_det_yolov8n_640.onnx" --meta-template "%PROJECT_ROOT%\configs\model_meta.template.json"
set EXIT_CODE=%ERRORLEVEL%
echo.
if not "%EXIT_CODE%"=="0" (
  echo 命令执行失败，退出码 %EXIT_CODE%。
) else (
  echo 命令执行完成。
)
pause
exit /b %EXIT_CODE%
