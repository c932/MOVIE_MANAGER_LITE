from pathlib import Path

import pytest

from scraper.scrape_models import ScrapeError


def video(root: Path, name: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    return path


@pytest.mark.parametrize(('name', 'expected'), [
    ('The.Matrix.1999.1080p.BluRay.x264-GROUP.mkv', ('The Matrix', '1999')),
    ('流浪地球2 (2023) 2160p WEB-DL.mkv', ('流浪地球2', '2023')),
    ('1917.2019.1080p.mkv', ('1917', '2019')),
    ('2001.A.Space.Odyssey.1968.4K.mkv', ('2001 A Space Odyssey', '1968')),
    ('无年份电影.mkv', ('无年份电影', '')),
])
def test_guess_title_and_year(name, expected):
    from scraper.media_discovery import guess_title_year
    assert guess_title_year(name) == expected


def test_discovery_extensions_overlap_blacklists_and_fragments(tmp_path):
    from scraper.media_discovery import discover_videos
    good = [video(tmp_path, f'电影{i}.2020{ext}') for i, ext in enumerate(
        ('.MKV', '.mP4', '.AVI', '.MOV', '.M2TS', '.TS'))]
    for name in ('sample.mkv', 'movie-sample.mp4', 'movie.trailer.mkv',
                 'extras/clip.mkv', 'BDMV/STREAM/00001.m2ts', 'VIDEO_TS/a.ts',
                 'Extras-Grym/a.mkv', 'secret.2020.mkv', 'ignore.txt'):
        video(tmp_path, name)
    targets = discover_videos([tmp_path, tmp_path, good[0]],
                             blacklist_folders=['Extras-Grym'],
                             blacklist_patterns=[r'secret.*'])
    assert {t.video_path for t in targets} == set(good)
    assert len(targets) == 6
    assert all(t.nfo_stamp is None and not t.existing for t in targets)


def test_nfo_paths_stamps_and_corruption_are_preserved(tmp_path):
    from scraper.media_discovery import discover_videos
    one = video(tmp_path, 'one/A.MKV')
    legacy = one.parent / 'movie.nfo'
    legacy.write_text('<movie><title>原片名</title><year>1998</year></movie>', encoding='utf-8')
    two = video(tmp_path, 'two/B.mp4')
    broken = two.with_suffix('.nfo')
    broken.write_text('<movie>broken', encoding='utf-8')
    three = video(tmp_path, 'three/C.mp4')
    exact = three.with_suffix('.NFO')
    exact.write_text('<movie/>', encoding='utf-8')
    targets = {t.video_path: t for t in discover_videos([tmp_path])}
    assert targets[one].nfo_path == legacy
    assert targets[one].existing and targets[one].title == '原片名'
    assert targets[one].year == '1998'
    assert targets[one].nfo_stamp == (legacy.stat().st_mtime_ns, legacy.stat().st_size)
    assert targets[two].existing and 'NFO' in targets[two].error
    assert targets[two].nfo_stamp == (broken.stat().st_mtime_ns, broken.stat().st_size)
    assert targets[three].nfo_path == exact
    assert not one.with_suffix('.nfo').exists()


def test_movie_nfo_never_shared_between_two_videos_even_for_one_explicit_path(tmp_path):
    from scraper.media_discovery import discover_videos
    a = video(tmp_path, 'A.mkv')
    b = video(tmp_path, 'B.mp4')
    (tmp_path / 'movie.nfo').write_text('<movie/>')
    assert {t.nfo_path for t in discover_videos([a, b])} == {a.with_suffix('.nfo'), b.with_suffix('.nfo')}
    assert discover_videos([a])[0].nfo_path == a.with_suffix('.nfo')


def test_parent_name_used_for_generic_video_name(tmp_path):
    from scraper.media_discovery import discover_videos
    video(tmp_path, 'Arrival.2016.1080p/movie.mkv')
    target = discover_videos([tmp_path])[0]
    assert (target.title, target.year) == ('Arrival', '2016')


def test_cancelled_and_unreadable_scan_never_look_like_success(tmp_path, monkeypatch):
    from scraper.media_discovery import discover_videos
    def cancel():
        raise ScrapeError('已取消')
    with pytest.raises(ScrapeError, match='取消'):
        discover_videos([tmp_path], check_cancelled=cancel)
    with pytest.raises(ScrapeError):
        discover_videos([tmp_path / 'missing'])
    import os
    def denied(*args):
        raise PermissionError('denied')
    monkeypatch.setattr(os, 'scandir', denied)
    with pytest.raises(ScrapeError):
        discover_videos([tmp_path])


def test_boolean_cancellation_and_invalid_blacklist(tmp_path):
    from scraper.media_discovery import discover_videos
    video(tmp_path, 'A.mp4')
    with pytest.raises(ScrapeError, match='取消'):
        discover_videos([tmp_path], check_cancelled=lambda: True)
    with pytest.raises(ScrapeError):
        discover_videos([tmp_path], blacklist_patterns=['['])


def test_non_movie_nfo_is_damaged_and_never_treated_as_missing(tmp_path):
    from scraper.media_discovery import discover_videos
    path = video(tmp_path, 'A.mp4')
    path.with_suffix('.nfo').write_text('<tvshow/>')
    target = discover_videos([tmp_path])[0]
    assert target.existing and target.error and target.nfo_stamp is not None


def junction(link: Path, destination: Path) -> None:
    import os
    import subprocess
    if os.name != 'nt':
        pytest.skip('此回归需要真实 Windows junction')
    subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(destination)],
                   check=True, capture_output=True)
    assert link.is_dir() and link.resolve() == destination.resolve()
    # Python 3.11 的 junction 不属于符号链接，不能依赖 is_symlink 排除。
    assert not link.is_symlink()


def test_windows_junction_cannot_escape_explicit_library_root(tmp_path):
    from scraper.media_discovery import discover_videos
    local = video(tmp_path, 'library/Inside.mkv')
    outside = video(tmp_path, 'outside/Outside.mkv')
    junction(local.parent / 'linked', outside.parent)
    targets = discover_videos([local.parent])
    assert [target.video_path for target in targets] == [local]


def test_windows_junction_explicit_root_still_scans_and_deduplicates(tmp_path):
    from scraper.media_discovery import discover_videos
    local = video(tmp_path, 'library/Inside.mkv')
    outside = video(tmp_path, 'outside/Outside.mkv')
    link = local.parent / 'linked'
    junction(link, outside.parent)
    assert [target.video_path for target in discover_videos([link])] == [outside]
    assert {target.video_path for target in discover_videos([local.parent, link, outside.parent])} == {local, outside}


@pytest.mark.parametrize('existing', [False, True])
@pytest.mark.parametrize('explicit_file', [False, True])
@pytest.mark.parametrize('second_stem', ['Film', 'film'])
def test_same_stem_videos_mark_nfo_conflict_and_cannot_save(tmp_path, existing, explicit_file, second_stem):
    from scraper.media_discovery import discover_videos
    from scraper.scrape_models import ScrapeDraft
    from scraper.scrape_service import ScrapeService
    a = video(tmp_path, 'Film.mkv')
    b = video(tmp_path, f'{second_stem}.mp4')
    other = video(tmp_path, 'Other.mkv')
    nfo = a.with_suffix('.nfo')
    original = b'<movie><title>Film</title></movie>'
    if existing:
        nfo.write_bytes(original)
    targets = discover_videos([a] if explicit_file else [tmp_path])
    conflicted = [target for target in targets if target.video_path in {a, b}]
    assert len(conflicted) == (1 if explicit_file else 2)
    for target in conflicted:
        assert '冲突' in target.error and 'NFO' in target.error
        with pytest.raises(ScrapeError, match='冲突'):
            ScrapeService().save(ScrapeDraft(target, confirmed=True), metadata_only=True)
    if not explicit_file:
        assert not next(target for target in targets if target.video_path == other).error
    if existing:
        assert nfo.read_bytes() == original
    else:
        assert not nfo.exists()


def test_same_stem_in_different_directories_has_no_conflict(tmp_path):
    from scraper.media_discovery import discover_videos
    video(tmp_path, 'one/Film.mkv')
    video(tmp_path, 'two/Film.mp4')
    targets = discover_videos([tmp_path])
    assert len(targets) == 2 and not any(target.error for target in targets)


def test_unknown_nfo_encoding_marks_one_bad_target_and_continues(tmp_path):
    from scraper.media_discovery import discover_videos
    bad = video(tmp_path, 'Bad.mkv')
    good = video(tmp_path, 'Good.mp4')
    nfo = bad.with_suffix('.nfo')
    original = b'<?xml version="1.0" encoding="unknown-encoding"?><movie/>'
    nfo.write_bytes(original)
    targets = {target.video_path: target for target in discover_videos([tmp_path])}
    assert set(targets) == {bad, good}
    assert targets[bad].existing and 'NFO' in targets[bad].error
    assert targets[bad].nfo_path == nfo
    assert targets[bad].nfo_stamp == (nfo.stat().st_mtime_ns, len(original))
    assert not targets[good].error and not targets[good].existing
    assert nfo.read_bytes() == original
