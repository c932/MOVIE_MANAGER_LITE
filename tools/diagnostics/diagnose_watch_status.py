"""
诊断观看状态筛选问题
"""
import json
import os
from utils.app_paths import resolve_data_file

print("=" * 80)
print("观看状态诊断报告")
print("=" * 80)

# 1. 检查 watch_history.json
history_file = resolve_data_file("watch_history.json")
if history_file.exists():
    with open(history_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    print(f"\n✓ watch_history.json 存在")
    print(f"  已观看电影数: {data.get('total', 0)}")
    print(f"\n  已观看的NFO路径:")
    for path in data.get('watched', []):
        normalized = os.path.normpath(path).lower()
        print(f"    原始: {path}")
        print(f"    规范化: {normalized}")
        print()
else:
    print(f"\n✗ watch_history.json 不存在")

print("=" * 80)
print("\n说明：")
print("1. 如果 watch_history.json 中有已观看电影，但筛选显示为空")
print("   → 说明 all_movies 中的 movie.watched 没有正确更新")
print()
print("2. 请重启应用并提供以下日志：")
print("   - 启动时: '加载已观看电影' 的日志")
print("   - 切换观看状态时: '观看状态切换' 和 '更新电影观看状态' 的日志")
print("   - 点击筛选按钮时: '开始应用过滤器' 和 '当前已观看电影数' 的日志")
print()
print("3. 如果看到 '✗ 未找到匹配的电影'，请比较:")
print("   - watch_history.json 中的路径")
print("   - 日志中的 '示例路径' 和 '示例规范化'")
print("=" * 80)
