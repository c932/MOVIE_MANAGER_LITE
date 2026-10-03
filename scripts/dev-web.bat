@echo off
REM 本地开发启动脚本（Windows）
REM 同时启动：Vite 前端 + 电影墙后端 + 游戏墙后端

cd /d "%~dp0"

set "DATA_MOVIE=%TEMP%\mml-movie-dev"
set "DATA_GAME=%TEMP%\mml-game-dev"
set "PYTHONPATH=.;webapp\backend"

echo ==========================================
echo  媒体墙本地开发服务器
echo ==========================================
echo.
echo 数据目录：
echo   电影墙：%DATA_MOVIE%
echo   游戏墙：%DATA_GAME%
echo.
echo 访问地址：
echo   前端：http://localhost:5173
echo   电影墙 API：http://127.0.0.1:8010
echo   游戏墙 API：http://127.0.0.1:8011
echo.
echo 按 Ctrl+C 停止所有服务
echo.

start "Vite Frontend" cmd /k "cd webapp\frontend && npm run dev"
timeout /t 2 >nul

start "Movie Service" cmd /k "set MML_DATA_DIR=%DATA_MOVIE% && set PYTHONPATH=%PYTHONPATH% && .venv\Scripts\python.exe -m uvicorn movie_service.main:app --host 127.0.0.1 --port 8010"
timeout /t 2 >nul

start "Game Service" cmd /k "set MML_DATA_DIR=%DATA_GAME% && set APP_DIR_NAME_OVERRIDE=LocalGameWall && set PYTHONPATH=%PYTHONPATH% && .venv\Scripts\python.exe -m uvicorn game_service.main:app --host 127.0.0.1 --port 8011"

echo 服务已启动，请访问 http://localhost:5173
pause
