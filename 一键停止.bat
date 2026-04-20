@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

if not exist app.pid (
  echo 未找到 app.pid，未发现可停止的实例。
  exit /b 1
)

set /p APP_PID=<app.pid
if "%APP_PID%"=="" (
  echo app.pid 为空。
  del /f /q app.pid >nul 2>nul
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -Command "if (Get-Process -Id %APP_PID% -ErrorAction SilentlyContinue) { Stop-Process -Id %APP_PID% -ErrorAction SilentlyContinue; Start-Sleep -Milliseconds 300 }"
del /f /q app.pid >nul 2>nul
echo 已尝试停止进程 PID=%APP_PID%

