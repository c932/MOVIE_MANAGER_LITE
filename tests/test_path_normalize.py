"""
测试路径规范化功能
"""
import os
import tempfile
import uuid
from utils.watch_history import WatchHistoryManager

# 测试不同格式的路径
test_paths = [
    "\\\\192.168.50.100\\movie\\2026\\test.nfo",
    "//192.168.50.100/movie/2026/test.nfo",
    "\\\\192.168.50.100/movie\\2026/test.nfo",  # 混合分隔符
]

print("路径规范化测试:")
print("=" * 80)

for path in test_paths:
    normalized = WatchHistoryManager.normalize_path(path)
    print(f"\n原始路径: {path}")
    print(f"规范化后: {normalized}")

# 测试所有路径是否被视为相同
normalized_paths = [WatchHistoryManager.normalize_path(p) for p in test_paths]
print("\n" + "=" * 80)
print(f"所有路径规范化后是否相同: {len(set(normalized_paths)) == 1}")
print(f"唯一规范化路径: {set(normalized_paths)}")

# 测试 WatchHistoryManager
print("\n" + "=" * 80)
print("测试 WatchHistoryManager:")
temp_history_file = os.path.join(
    tempfile.gettempdir(), f"movie_manager_test_history_{uuid.uuid4().hex}.json"
)
manager = WatchHistoryManager(temp_history_file)

# 用第一种格式标记为已观看
manager.mark_watched(test_paths[0])
print(f"\n标记已观看: {test_paths[0]}")

# 用其他格式检查
for path in test_paths[1:]:
    is_watched = manager.is_watched(path)
    print(f"检查 '{path}': {is_watched}")

# 清理测试文件
if os.path.exists(temp_history_file):
    os.remove(temp_history_file)
    print("\n已清理测试文件")
