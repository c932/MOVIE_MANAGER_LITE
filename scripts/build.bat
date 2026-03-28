@echo off
chcp 65001 >nul
pushd "%~dp0.."
echo ========================================
echo 本地电影墙 - 打包脚本
echo ========================================
echo.

REM 检查 PyInstaller 是否安装
python -c "import PyInstaller" 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [错误] 未检测到 PyInstaller，正在安装...
    pip install pyinstaller
    if %ERRORLEVEL% NEQ 0 (
        echo [失败] PyInstaller 安装失败
        pause
        exit /b 1
    )
)

echo [1/3] 清理旧的构建文件...
if exist "dist" rmdir /s /q "dist"
if exist "build" rmdir /s /q "build"

echo [2/3] 开始打包...
pyinstaller --clean packaging\Movie_Manager_Lite.spec

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [失败] 打包过程出错
    pause
    exit /b 1
)

echo [3/3] 打包完成！
echo.
echo ========================================
echo 输出目录: dist\本地电影墙\
echo 主程序: dist\本地电影墙\本地电影墙.exe
echo ========================================
echo.
echo 注意：首次运行时，程序会在当前目录创建：
echo   - data\config.json (配置文件)
echo   - data\movie_cache.json (电影缓存)
echo   - data\watch_history.json (观看历史)
echo   - data\favorites.json (收藏列表)
echo.
pause
popd
