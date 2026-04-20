@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

if exist app.pid (
  set /p OLD_PID=<app.pid
  if not "%OLD_PID%"=="" (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "if (Get-Process -Id %OLD_PID% -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }"
    if not errorlevel 1 (
      echo 检测到程序已在运行，PID=%OLD_PID%
      echo 如需重启，请先执行一键停止.bat
      exit /b 1
    )
  )
  del /f /q app.pid >nul 2>nul
)

set "PY_CANDIDATE_1=%~dp0..\Propainter1.6\Miniconda3\python.exe"
set "PY_CANDIDATE_2=python"
set "PYTHON_EXE="

if exist "%PY_CANDIDATE_1%" (
  "%PY_CANDIDATE_1%" -c "import PySide6" >nul 2>nul
  if not errorlevel 1 set "PYTHON_EXE=%PY_CANDIDATE_1%"
)

if "%PYTHON_EXE%"=="" (
  where %PY_CANDIDATE_2% >nul 2>nul
  if errorlevel 1 (
    echo 未找到可用的 Python。
    echo 需要安装 PySide6：pip install PySide6
    exit /b 1
  )
  %PY_CANDIDATE_2% -c "import PySide6" >nul 2>nul
  if errorlevel 1 (
    echo 当前 Python 未安装 PySide6。
    echo 请执行：pip install PySide6
    exit /b 1
  )
  set "PYTHON_EXE=%PY_CANDIDATE_2%"
)

if exist app.out.log del /f /q app.out.log >nul 2>nul
if exist app.err.log del /f /q app.err.log >nul 2>nul
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=Start-Process -FilePath '%PYTHON_EXE%' -ArgumentList 'main.py' -WorkingDirectory '%~dp0' -RedirectStandardOutput '%~dp0app.out.log' -RedirectStandardError '%~dp0app.err.log' -PassThru; if (-not $p) { exit 2 }; $p.Id | Out-File -FilePath '%~dp0app.pid' -Encoding ascii; Start-Sleep -Milliseconds 1000; if (Get-Process -Id $p.Id -ErrorAction SilentlyContinue) { exit 0 } else { exit 3 }"
if errorlevel 1 (
  echo 程序启动失败，请查看 app.err.log
  del /f /q app.pid >nul 2>nul
  exit /b 1
)
set /p APP_PID=<app.pid
echo 已启动 MP4 视频区域模糊编辑器，PID=%APP_PID%

