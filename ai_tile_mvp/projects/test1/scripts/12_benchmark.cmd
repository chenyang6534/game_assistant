@echo off
setlocal
set PROJECT_ROOT=%~dp0..
set AI_ROOT=%PROJECT_ROOT%\..\..

python "%AI_ROOT%\scripts\benchmark_onnx_tile.py" --model "%PROJECT_ROOT%\models\detector\test1_det_yolov8n_640.onnx" --image-dir "%PROJECT_ROOT%\datasets\detection\images\test" --label-dir "%PROJECT_ROOT%\datasets\detection\labels\test" --output-dir "%PROJECT_ROOT%\outputs\benchmark_preview"
set EXIT_CODE=%ERRORLEVEL%
echo.
if not "%EXIT_CODE%"=="0" (
  echo 命令执行失败，退出码 %EXIT_CODE%。
) else (
  echo 命令执行完成。
)
pause
exit /b %EXIT_CODE%
