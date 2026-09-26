@echo off
chcp 65001 >nul
REM 一键启动 - 电影墙 / 游戏墙选择器
REM 自动检查依赖，让用户选择启动哪个应用
REM 双击运行，窗口不会自动关闭

pushd "%~dp0.."

echo =========================================
echo   Local Movie Wall  /  Local Game Wall
echo   本地电影海报墙  /  本地游戏海报墙
echo =========================================
echo.

REM 检查 Python 是否安装
python --version >/dev/null 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3.10+
    echo 下载地址: https://www.python.org/downloads/
    echo.
    pause
    popd
    exit /b 1
)

echo [OK] Python 环境检测成功
echo.

REM 检查依赖是否安装
python -c "import PyQt6" >/dev/null 2>&1
if errorlevel 1 (
    echo [!] 检测到缺少依赖，正在自动安装...
    echo.
    pip install -r requirements.txt
    if errorlevel 1 (
        echo [错误] 依赖安装失败
        echo.
        pause
        popd
        exit /b 1
    )
    echo.
    echo [OK] 依赖安装完成
) else (
    echo [OK] PyQt6 依赖已安装
)

echo.
echo 请选择要启动的应用:
echo.
echo   [1] 电影墙  Local Movie Wall
echo   [2] 游戏墙  Local Game Wall
echo   [3] 同时启动两个应用
echo   [0] 退出
echo.

set /p choice=请输入选择 (0-3):

if "%choice%"=="1" goto movie_wall
if "%choice%"=="2" goto game_wall
if "%choice%"=="3" goto both
if "%choice%"=="0" goto end
echo.
echo [!] 无效选择
goto end

:movie_wall
echo.
echo [启动] 正在启动电影墙...
start "" python main.py
echo [OK] 电影墙已启动
goto end

:game_wall
echo.
echo [启动] 正在启动游戏墙...
start "" python game_main.py
echo [OK] 游戏墙已启动
goto end

:both
echo.
echo [启动] 正在同时启动两个应用...
start "" python main.py
echo [OK] 电影墙已启动
start "" python game_main.py
echo [OK] 游戏墙已启动
echo.
echo 两个应用已启动，关闭此窗口不影响运行。

:end
echo.
pause
popd
