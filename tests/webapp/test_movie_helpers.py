"""
电影墙 API 测试共享工具（本文件不含测试用例）。

约定：
- 只允许在 `service_data_dir` 提供的临时目录里造数据，绝不触碰真实 data/；
- 通过 `movie_client()` 创建的每个 app 实例都指向该临时目录；
- 网络相关行为一律由各测试文件 monkeypatch。
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

API = "/api/movie"

# 契约 2.1 MovieListItem / MovieDetail 的字段集合
MOVIE_DTO_KEYS = (
    "id", "title", "original_title", "year", "premiered", "plot", "tagline",
    "runtime", "file_size", "set_name", "genres", "countries", "tags",
    "rating", "rating_source", "ratings", "user_rating", "watched", "favorite",
    "directors", "actors", "resolution", "hdr_type", "video_codec", "audio_codec",
    "imdb_id", "tmdb_id", "douban_url", "video_path", "nfo_path", "poster_path",
    "fanart_path", "added_time", "has_poster", "has_fanart", "rank",
)

LONG_PLOT = "一段很长的剧情简介。" * 40  # > 200 字符，用于列表截断断言


def nfo_xml(
    *,
    title: str,
    original_title: str = "",
    year: str = "2004",
    premiered: str = "2004-10-29",
    plot: str = "剧情简介",
    tagline: str = "",
    runtime: str = "103",
    genres: Sequence[str] = ("恐怖", "悬疑"),
    countries: Sequence[str] = ("美国",),
    tags: Sequence[str] = (),
    directors: Sequence[str] = ("詹姆斯·温",),
    actors: Sequence[Dict[str, str]] = (),
    ratings: Sequence[tuple] = (("douban", 8.5), ("imdb", 8.4)),
    uniqueids: Sequence[tuple] = (("imdb", "tt0387564"),),
    width: int = 1920,
    height: int = 1080,
    video_codec: str = "h264",
    audio_codec: str = "dts",
    set_name: str = "",
) -> str:
    """构造一段 Kodi 风格的 NFO 文本。"""
    def esc(text: str) -> str:
        return (
            str(text)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    lines = ['<?xml version="1.0" encoding="utf-8"?>', "<movie>"]
    lines.append(f"  <title>{esc(title)}</title>")
    if original_title:
        lines.append(f"  <originaltitle>{esc(original_title)}</originaltitle>")
    if year:
        lines.append(f"  <year>{esc(year)}</year>")
    if premiered:
        lines.append(f"  <premiered>{esc(premiered)}</premiered>")
    lines.append(f"  <plot>{esc(plot)}</plot>")
    if tagline:
        lines.append(f"  <tagline>{esc(tagline)}</tagline>")
    lines.append(f"  <runtime>{esc(runtime)}</runtime>")
    if set_name:
        lines.append(f"  <set><name>{esc(set_name)}</name></set>")
    if ratings:
        lines.append("  <ratings>")
        for name, value in ratings:
            lines.append(
                f'    <rating name="{name}" max="10"><value>{value}</value></rating>'
            )
        lines.append("  </ratings>")
    for index, (id_type, value) in enumerate(uniqueids):
        default = ' default="true"' if index == 0 else ""
        lines.append(f'  <uniqueid type="{id_type}"{default}>{esc(value)}</uniqueid>')
    for genre in genres:
        lines.append(f"  <genre>{esc(genre)}</genre>")
    for country in countries:
        lines.append(f"  <country>{esc(country)}</country>")
    for tag in tags:
        lines.append(f"  <custom>{esc(tag)}</custom>")
    for director in directors:
        lines.append(f"  <director>{esc(director)}</director>")
    for actor in actors:
        lines.append("  <actor>")
        lines.append(f"    <name>{esc(actor['name'])}</name>")
        if actor.get("role"):
            lines.append(f"    <role>{esc(actor['role'])}</role>")
        lines.append("  </actor>")
    lines.append("  <fileinfo><streamdetails>")
    lines.append(
        f"    <video><width>{width}</width><height>{height}</height>"
        f"<codec>{video_codec}</codec></video>"
    )
    lines.append(f"    <audio><codec>{audio_codec}</codec></audio>")
    lines.append("  </streamdetails></fileinfo>")
    lines.append("</movie>")
    return "\n".join(lines)


def make_poster(path: Path, size=(12, 18)) -> None:
    """写一张合法的小 JPEG 占位海报。"""
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (180, 40, 40)).save(path, format="JPEG")


def add_movie(folder: Path, stem: str, *, poster: bool = True, **nfo_kwargs) -> Path:
    """在 folder 下造一部电影：NFO + 同名视频占位文件 (+poster.jpg)。"""
    folder.mkdir(parents=True, exist_ok=True)
    nfo_path = folder / f"{stem}.nfo"
    nfo_path.write_text(nfo_xml(**nfo_kwargs), encoding="utf-8")
    (folder / f"{stem}.mkv").write_bytes(b"movie")
    if poster:
        make_poster(folder / "poster.jpg")
    return nfo_path


def default_actors(count: int = 10) -> List[Dict[str, str]]:
    return [{"name": f"演员{i:02d}", "role": f"角色{i:02d}"} for i in range(count)]


def build_library(library_root: Path) -> Dict[str, Path]:
    """
    造一个含 2 部电影的迷你媒体库：
    - 电锯惊魂（长简介 + 10 位演员 → 验证列表截断）
    - 疯狂动物城（常规）
    返回 {"root": 目录, "saw": NFO 路径, "zootopia": NFO 路径}
    """
    saw = add_movie(
        library_root / "Saw",
        "Saw",
        title="电锯惊魂",
        original_title="Saw",
        year="2004",
        genres=("恐怖", "悬疑"),
        countries=("美国",),
        directors=("詹姆斯·温",),
        actors=default_actors(10),
        plot=LONG_PLOT,
        ratings=(("douban", 8.5), ("imdb", 8.4)),
        uniqueids=(("imdb", "tt0387564"),),
    )
    zootopia = add_movie(
        library_root / "Zootopia",
        "Zootopia",
        title="疯狂动物城",
        original_title="Zootopia",
        year="2016",
        premiered="2016-03-04",
        genres=("喜剧", "动作"),
        countries=("美国",),
        directors=("拜伦·霍华德",),
        actors=[
            {"name": "金妮弗·古德温", "role": "朱迪"},
            {"name": "杰森·贝特曼", "role": "尼克"},
            {"name": "伊德里斯·艾尔巴", "role": "牛局长"},
        ],
        plot="兔子朱迪成为警察。",
        ratings=(("douban", 9.2),),
        uniqueids=(("imdb", "tt2948356"),),
        width=1280,
        height=720,
    )
    return {"root": library_root, "saw": saw, "zootopia": zootopia}


@contextmanager
def movie_client(data_dir: Path):
    """在指定临时数据目录上创建电影墙 app 并以 TestClient 打开。"""
    from fastapi.testclient import TestClient

    from movie_service.main import create

    with TestClient(create(data_dir=str(data_dir))) as client:
        yield client


def set_movie_paths(client, paths: Iterable[Path]) -> None:
    response = client.put(f"{API}/settings", json={"movie_paths": [str(p) for p in paths]})
    assert response.status_code == 200, response.text


def wait_job(client, job_id: str, timeout: float = 20.0) -> Dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = client.get(f"{API}/jobs/{job_id}")
        assert response.status_code == 200, response.text
        job = response.json()
        if job["status"] in ("done", "error", "cancelled"):
            return job
        time.sleep(0.02)
    raise AssertionError(f"任务 {job_id} 超时未结束")


def refresh(client, *, force: bool = True, expect: str = "done") -> Dict[str, Any]:
    """提交媒体库刷新并等待结束，返回 job（result 在 job["result"]）。"""
    response = client.post(f"{API}/library/refresh", json={"force": force})
    assert response.status_code == 200, response.text
    job = wait_job(client, response.json()["job_id"])
    assert job["status"] == expect, f"刷新任务状态={job['status']} error={job['error']}"
    return job


def prepare_library(client, library_root: Path) -> Dict[str, Any]:
    """配置电影目录并全量刷新一次，返回刷新结果。"""
    set_movie_paths(client, [library_root])
    return refresh(client, force=True)["result"]


def movies_of(client, **params) -> List[Dict[str, Any]]:
    response = client.get(f"{API}/movies", params=params)
    assert response.status_code == 200, response.text
    return response.json()["movies"]


def find_movie(client, title: str) -> Dict[str, Any]:
    for movie in movies_of(client):
        if movie["title"] == title:
            return movie
    raise AssertionError(f"列表中没有标题为 {title!r} 的电影")
