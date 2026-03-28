"""
测试脚本：模拟评分筛选逻辑
"""
from pathlib import Path
from parsers.nfo_parser import NFOParser

def test_filter_logic():
    """模拟apply_filters中的评分筛选逻辑"""
    sample_dir = Path("e:/My Code/Movie_Manager_Lite/sample")
    
    if not sample_dir.exists():
        print(f"sample目录不存在: {sample_dir}")
        return
    
    parser = NFOParser()
    nfo_files = list(sample_dir.glob("*.nfo"))
    
    # 解析所有电影
    all_movies = []
    for nfo_file in nfo_files:
        try:
            movie = parser.parse(str(nfo_file))
            all_movies.append(movie)
        except Exception as e:
            print(f"解析失败 {nfo_file.name}: {e}")
    
    print(f"\n共解析 {len(all_movies)} 部电影\n")
    print("=" * 80)
    
    # 测试不同的评分筛选值
    test_ratings = [0.0, 6.0, 7.0, 8.0, 9.0]
    
    for min_rating in test_ratings:
        print(f"\n测试评分筛选: min_rating = {min_rating}")
        print("-" * 80)
        
        filtered_movies = []
        
        for movie in all_movies:
            # 模拟评分筛选逻辑
            if min_rating > 0:
                print(f"  检查 '{movie.title}': rating={movie.rating} (type={type(movie.rating).__name__}), min={min_rating}")
                print(f"    rating < min_rating: {movie.rating} < {min_rating} = {movie.rating < min_rating}")
                print(f"    是否跳过: {movie.rating < min_rating}")
                
                if movie.rating < min_rating:
                    print(f"    ✗ 跳过（评分不足）")
                    continue
                else:
                    print(f"    ✓ 通过")
            
            filtered_movies.append(movie)
        
        print(f"\n  结果: {len(filtered_movies)}/{len(all_movies)} 部电影通过筛选")
        
        for movie in filtered_movies:
            print(f"    - {movie.title} (评分: {movie.rating})")
        
        print("=" * 80)

if __name__ == "__main__":
    test_filter_logic()
