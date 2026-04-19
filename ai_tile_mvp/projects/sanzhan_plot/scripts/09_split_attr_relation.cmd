@echo off
setlocal
set PROJECT_ROOT=%~dp0..
set AI_ROOT=%PROJECT_ROOT%\..\..

python "%AI_ROOT%\scripts\split_attribute_classification_dataset.py" --source-raw-root "%PROJECT_ROOT%\datasets\attribute_cls\relation\raw" --output-root "%PROJECT_ROOT%\datasets\attribute_cls\relation" --clear-output
set EXIT_CODE=%ERRORLEVEL%
echo.
if not "%EXIT_CODE%"=="0" (
  echo 命令执行失败，退出码 %EXIT_CODE%。
) else (
  echo 命令执行完成。
)
pause
exit /b %EXIT_CODE%
