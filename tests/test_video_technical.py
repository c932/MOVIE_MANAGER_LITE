from pathlib import Path

import pytest

from models.movie import Movie
from parsers.nfo_parser import NFOParser
from utils.cache_manager import CacheManager
from utils.video_technical import technical_from_filename, resolution_from_dimensions


@pytest.mark.parametrize('width,height', [('0','0'), ('',''), ('N/A','2160'), ('3840','0'), ('-1','480')])
def test_unknown_dimensions_are_not_sd(width, height):
    assert resolution_from_dimensions(width,height) == ''


@pytest.mark.parametrize('name,resolution,hdr', [
    ('Project.Hail.Mary.2026.2160p.iT.WEB-DL.H265.DV.HDR.DDP5.1.Atmos.mkv','4K','Dolby Vision / HDR'),
    ('Film.1080p.HDR10+.mkv','1080p','HDR10+'), ('Film.8K.DoVi.mkv','8K','Dolby Vision'),
    ('Not4KFilm.WEB.mkv','',''), ('/Movies.2160p/Film.mkv','',''),
])
def test_filename_tokens_are_explicit_and_from_basename_only(name,resolution,hdr):
    assert technical_from_filename(name) == (resolution,hdr)


def make_nfo(root: Path, stem: str, video: str) -> Path:
    root.mkdir(parents=True,exist_ok=True)
    (root/(stem+'.mkv')).write_bytes(b'video')
    path=root/(stem+'.nfo')
    path.write_text('<movie><title>测试</title><fileinfo><streamdetails>'+video+'</streamdetails></fileinfo></movie>',encoding='utf8')
    return path


def test_zero_nfo_dimensions_fall_back_to_2160p_without_modifying_nfo(tmp_path):
    nfo=make_nfo(tmp_path,'Project.Hail.Mary.2026.2160p.DV.HDR','<video><width>0</width><height>0</height></video>')
    before=nfo.read_bytes()
    movie=NFOParser.parse(str(nfo))
    assert movie.resolution=='4K' and movie.hdr_type=='Dolby Vision / HDR'
    assert movie.video_width==movie.video_height==0
    assert nfo.read_bytes()==before


def test_verified_sd_dimensions_win_over_misleading_filename_and_survive_cache(tmp_path):
    nfo=make_nfo(tmp_path,'Film.2160p','<video><width>640</width><height>480</height></video>')
    movie=NFOParser.parse(str(nfo))
    assert movie.resolution=='480p'
    cache=CacheManager(str(tmp_path/'cache.json'))
    restored=cache._deserialize_movie(cache._serialize_movie(movie))
    assert (restored.resolution,restored.video_width,restored.video_height)==('480p',640,480)


def test_valid_main_stream_wins_over_zero_placeholder(tmp_path):
    nfo=make_nfo(tmp_path,'Film','<video><width>0</width><height>0</height></video><video><width>3840</width><height>1600</height><hdrtype>HDR10</hdrtype></video>')
    movie=NFOParser.parse(str(nfo))
    assert (movie.resolution,movie.video_width,movie.video_height,movie.hdr_type)==('4K',3840,1600,'HDR10')


def test_legacy_sd_cache_can_be_corrected_offline_from_explicit_filename(tmp_path):
    cache=CacheManager(str(tmp_path/'cache.json'))
    movie=cache._deserialize_movie({'title':'挽救计划','resolution':'SD','video_path':r'\\offline\share\Project.Hail.Mary.2026.2160p.DV.HDR.mkv'})
    assert movie.resolution=='4K' and movie.hdr_type=='Dolby Vision / HDR'
    assert Movie(resolution='SD',video_path=r'\\offline\4K\Film.mkv').resolution=='SD'
