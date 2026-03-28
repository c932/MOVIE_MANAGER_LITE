"""
测试观看状态筛选逻辑
"""
import json
from utils.app_paths import resolve_data_file

# 读取 watch_history.json
history_file = resolve_data_file("watch_history.json")

if history_file.exists():
    with open(history_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    print("观看历史记录内容:")
    print("=" * 80)
    print(f"总计: {data.get('total', 0)} 部已观看电影")
    print(f"\n已观看的NFO路径列表:")
    for path in data.get('watched', []):
        print(f"  - {path}")
    print("=" * 80)
else:
    print(f"watch_history.json 文件不存在: {history_file}")

# 测试筛选逻辑
print("\n筛选逻辑测试:")
print("=" * 80)

# 模拟电影对象
class FakeMovie:
    def __init__(self, title, nfo_path, watched):
        self.title = title
        self.nfo_path = nfo_path
        self.watched = watched

# 创建测试电影列表
movies = [
    FakeMovie("末日逃生2：迁移", "\\\\192.168.50.100\\movie\\2026\\末日逃生2：迁移.Greenland.2.Migration.2026.1080p.AMZN.WEB-DL.English.DDP5.1.H.264\\Greenland.2.Migration.2026.1080p.AMZN.WEB-DL.English.DDP5.1.H.264.nfo", True),
    FakeMovie("其他电影1", "path/to/movie1.nfo", False),
    FakeMovie("其他电影2", "path/to/movie2.nfo", False),
]

# 测试 watch_filter_mode = 2 (已观看)
watch_filter_mode = 2
filtered = []

print(f"\n测试筛选模式: {watch_filter_mode} (2=已观看)")
print("-" * 80)

for movie in movies:
    print(f"\n检查: {movie.title}")
    print(f"  watched = {movie.watched}")
    
    if watch_filter_mode == 1:  # 未观看
        if movie.watched:
            print(f"  → 跳过 (已观看)")
            continue
    elif watch_filter_mode == 2:  # 已观看
        if not movie.watched:
            print(f"  → 跳过 (未观看)")
            continue
    
    print(f"  → ✓ 通过筛选")
    filtered.append(movie)

print("\n" + "=" * 80)
print(f"筛选结果: {len(filtered)} / {len(movies)} 部电影")
for m in filtered:
    print(f"  - {m.title} (watched={m.watched})")
