"""
快速诊断：打印所有电影的观看状态
"""
from pathlib import Path
from parsers.nfo_parser import NFOParser
from utils.watch_history import WatchHistoryManager
import os

print("=" * 80)
print("电影观看状态诊断")
print("=" * 80)

# 初始化观看历史管理器
watch_history = WatchHistoryManager()
print(f"\n观看历史记录: {watch_history.get_watched_count()} 部已观看")
print(f"已观看的规范化路径:")
for path in watch_history.watched_movies:
    print(f"  - {path}")

# 扫描所有NFO文件
library_path = r"\\192.168.50.100\movie"
nfo_files = list(Path(library_path).rglob("*.nfo"))
print(f"\n找到 {len(nfo_files)} 个NFO文件")

print("\n" + "=" * 80)
print("每部电影的观看状态:")
print("=" * 80)

for idx, nfo_path in enumerate(nfo_files[:5], 1):  # 只显示前5个
    try:
        movie = NFOParser.parse(str(nfo_path))
        if movie:
            # 检查观看状态
            is_watched = watch_history.is_watched(str(nfo_path))
            
            print(f"\n{idx}. {movie.title}")
            print(f"   NFO路径: {nfo_path}")
            print(f"   规范化: {WatchHistoryManager.normalize_path(str(nfo_path))}")
            print(f"   观看状态: {'✓ 已观看' if is_watched else '✗ 未观看'}")
    except Exception as e:
        print(f"\n{idx}. 解析失败: {nfo_path.name} - {e}")

print("\n" + "=" * 80)
print("\n提示：如果某部电影显示为'已观看'但筛选不工作，")
print("请检查 Movie 对象的 watched 属性是否正确设置。")
print("=" * 80)
