@echo off
REM Local Movie Wall 启动脚本
REM 自动检查依赖并启动程序

pushd "%~dp0.."

echo =========================================
echo   Local Movie Wall - 本地电影海报墙
echo =========================================
echo.

REM 检查 Python 是否安装
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3.8+
    echo 下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [✓] Python 环境检测成功
echo.

REM 检查依赖是否安装
python -c "import PyQt6" >nul 2>&1
if errorlevel 1 (
    echo [!] 检测到缺少依赖，正在自动安装...
    echo.
    pip install -r requirements.txt
    if errorlevel 1 (
        echo [错误] 依赖安装失败
        pause
        exit /b 1
    )
    echo.
    echo [✓] 依赖安装完成
) else (
    echo [✓] PyQt6 依赖已安装
)

echo.
echo [启动] 正在启动 Local Movie Wall...
echo.

REM 启动程序
python main.py

REM 捕获退出码
if errorlevel 1 (
    echo.
    echo [错误] 程序异常退出
    pause
)

popd
