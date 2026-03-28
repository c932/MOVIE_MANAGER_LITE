"""
测试脚本：检查所有电影的评分信息
"""
import sys
from pathlib import Path
from parsers.nfo_parser import NFOParser

def test_all_ratings():
    """扫描sample文件夹中所有.nfo文件并显示评分"""
    sample_dir = Path("e:/My Code/Movie_Manager_Lite/sample")
    
    if not sample_dir.exists():
        print(f"sample目录不存在: {sample_dir}")
        return
    
    parser = NFOParser()
    nfo_files = list(sample_dir.glob("*.nfo"))
    
    print(f"找到 {len(nfo_files)} 个NFO文件\n")
    print("=" * 80)
    
    for nfo_file in nfo_files:
        print(f"\n文件: {nfo_file.name}")
        
        try:
            movie = parser.parse(str(nfo_file))
            print(f"  标题: {movie.title}")
            print(f"  评分: {movie.rating} (类型: {type(movie.rating).__name__})")
            print(f"  年份: {movie.year}")
            print(f"  类型: {', '.join(movie.genres)}")
            print(f"  国家: {', '.join(movie.countries)}")
            
            # 检查评分是否 >= 7.0
            if movie.rating >= 7.0:
                print(f"  ✓ 评分 >= 7.0")
            else:
                print(f"  ✗ 评分 < 7.0")
                
        except Exception as e:
            print(f"  ✗ 解析失败: {e}")
        
        print("-" * 80)

if __name__ == "__main__":
    test_all_ratings()
