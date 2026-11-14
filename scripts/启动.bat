@echo off
chcp 65001 >nul
pushd "%~dp0.."
set "MOVIE_PYTHON=python"
if exist ".venv\Scripts\python.exe" set "MOVIE_PYTHON=.venv\Scripts\python.exe"

"%MOVIE_PYTHON%" --version >nul 2>&1
if errorlevel 1 (
  echo [错误] 请先安装 Python 3.10+。
  pause
  popd
  exit /b 1
)

"%MOVIE_PYTHON%" -c "import PyQt6" >nul 2>&1
if errorlevel 1 (
  "%MOVIE_PYTHON%" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo [错误] 依赖安装失败。
    pause
    popd
    exit /b 1
  )
)

echo 正在启动本地电影墙...
start "" "%MOVIE_PYTHON%" main.py
popd
