@echo off
chcp 65001 >nul
cd /d "%~dp0.."
set "MML_DEV_DATA=%TEMP%\mml-movie-dev"
set "PYTHONPATH=%CD%;%CD%\webapp\backend"
if not exist ".venv\Scripts\python.exe" (
  echo [错误] 请先创建 .venv 并安装项目依赖。
  exit /b 1
)
start "Movie Manager Lite API" cmd /k "set MML_DATA_DIR=%MML_DEV_DATA%&& .venv\Scripts\python.exe -m uvicorn movie_service.main:app --host 127.0.0.1 --port 8010"
start "Movie Manager Lite Frontend" cmd /k "cd webapp\frontend && npm run dev"
echo 前端地址：http://localhost:5173
