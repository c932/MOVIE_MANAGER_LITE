@echo off
chcp 65001 > nul
pushd "%~dp0.."
cls
echo ========================================
echo 观看状态筛选修复（v3.2）
echo ========================================
echo.
echo 已修复的BUG：
echo [X] 观看状态按钮被错误绑定到年份筛选器
echo [X] "全部"按钮的双重事件绑定冲突
echo.
echo 现在应该可以正常工作了！
echo.
echo 测试步骤：
echo 1. 等待媒体库扫描完成
echo 2. 点击"已观看"按钮 -> 应显示 1 部电影
echo 3. 点击"未观看"按钮 -> 应显示 18 部电影
echo 4. 点击"全部"按钮 -> 应显示 19 部电影
echo.
echo ========================================
echo.

python main.py

echo.
pause
popd
