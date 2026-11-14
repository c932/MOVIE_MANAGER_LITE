"""
网页版服务端只允许导入纯 Python 领域模块。

守护测试：确保 models / parsers / utils / scraper 的领域模块
在导入时不会连带拉起 PyQt6（Ubuntu 服务器无 GUI 环境）。
"""
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

DOMAIN_MODULES = [
    "models.movie",
    "parsers.nfo_parser",
    "utils.app_paths",
    "utils.config_manager",
    "utils.cache_manager",
    "utils.watch_history",
    "utils.favorite_manager",
    "utils.failed_movies_manager",
    "scraper",
    "scraper.douban_cli",
    "scraper.douban_ranking",
    "scraper.new_movie_checker",
    "scraper.scrape_models",
    "scraper.scrape_settings",
    "scraper.scrape_http",
    "scraper.metadata_sources",
    "scraper.media_discovery",
    "scraper.nfo_inspection",
    "scraper.scrape_persistence",
    "scraper.scrape_service",
    "scraper.scan_queue",
    "scraper.rating_enrichment",
    "scraper.imdb_provider",
    "scraper.imdb_ratings",
]


def test_domain_modules_import_without_pyqt():
    code = (
        "import sys\n"
        f"mods = {DOMAIN_MODULES!r}\n"
        "failed = []\n"
        "for m in mods:\n"
        "    try:\n"
        "        __import__(m)\n"
        "    except Exception as e:\n"
        "        failed.append(f'{m}: {type(e).__name__}: {e}')\n"
        "print('IMPORT_FAILURES=' + repr(failed))\n"
        "print('PYQT_LOADED=' + str('PyQt6' in sys.modules))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=120,
    )
    out = proc.stdout
    assert "IMPORT_FAILURES=[]" in out, f"导入失败: {out}\n{proc.stderr}"
    assert "PYQT_LOADED=False" in out, f"导入领域模块时拉起了 PyQt6: {out}"


def test_qt_tasks_still_exposed_via_lazy_getattr():
    """原导入路径保持可用（桌面版依赖此路径）。"""
    import scraper.douban_ranking
    import scraper.new_movie_checker

    assert scraper.douban_ranking.RankingFetcher.__name__ == "RankingFetcher"
    assert scraper.new_movie_checker.NewMovieFetcher.__name__ == "NewMovieFetcher"

    import scraper

    assert scraper.RankingFetcher.__name__ == "RankingFetcher"
    assert scraper.NewMovieFetcher.__name__ == "NewMovieFetcher"
