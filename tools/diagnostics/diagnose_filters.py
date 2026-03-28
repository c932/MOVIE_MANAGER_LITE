"""
诊断筛选器数据
检查扫描到的电影数量和筛选项
"""
import json
from utils.library_scanner import LibraryScanner
from utils.app_paths import resolve_data_file

# 加载配置
with open(resolve_data_file('config.json'), 'r', encoding='utf-8') as f:
    config = json.load(f)

movie_paths = config.get('movie_paths', [])
blacklist_folders = config.get('blacklist_folders', [])
blacklist_patterns = config.get('blacklist_patterns', [])

print(f"配置的电影路径: {movie_paths}")
print("\n开始扫描...")

# 扫描电影
scanner = LibraryScanner(movie_paths, blacklist_folders, blacklist_patterns)
movies = scanner.scan()

print(f"\n扫描完成！共找到 {len(movies)} 部电影\n")

# 统计筛选项
all_genres = set()
all_countries = set()
all_years = set()
all_tags = set()

for movie in movies:
    all_genres.update(movie.genres)
    all_countries.update(movie.countries)
    all_tags.update(movie.tags)
    if movie.year:
        all_years.add(movie.year)

print(f"类型数量: {len(all_genres)}")
print(f"类型列表: {sorted(all_genres)}")

print(f"\n国家数量: {len(all_countries)}")
print(f"国家列表: {sorted(all_countries)}")

print(f"\n年份数量: {len(all_years)}")
print(f"年份列表: {sorted(all_years, reverse=True)[:20]}")

print(f"\n自定义标签数量: {len(all_tags)}")
print(f"自定义标签列表: {sorted(all_tags)}")

# 显示前5部电影的详细信息
print("\n\n前5部电影详细信息:")
for i, movie in enumerate(movies[:5], 1):
    print(f"\n{i}. {movie.title}")
    print(f"   类型: {movie.genres}")
    print(f"   国家: {movie.countries}")
    print(f"   年份: {movie.year}")
    print(f"   标签: {movie.tags}")
