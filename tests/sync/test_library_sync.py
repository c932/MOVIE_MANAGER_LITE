from utils.library_sync import LibraryDatabase, movie_key


def record(title='电影', **fields):
    return dict(nfo_path=r'\\nas\movie\Film.nfo', title=title, year='2016', **fields)


def test_cross_platform_identity():
    assert movie_key(r'\\NAS\Movie\Film.nfo') == movie_key('//nas/movie/film.nfo')


def test_three_way_fields_and_conflicts(tmp_path):
    db = LibraryDatabase(tmp_path / 'library.db')
    mid = movie_key(record()['nfo_path'])
    first = db.push([{'id': mid, 'base': None, 'data': record()}])
    assert not first['conflicts']
    db.push([{'id': mid, 'base': record(), 'data': {'title': '服务器新标题'}}])
    result = db.push([{'id': mid, 'base': record(), 'data': {'title': '旧客户端修改', 'year': '2017'}}])
    assert result['conflicts'][0]['fields'] == ['title']
    assert db.snapshot()['records'][0]['data']['title'] == '服务器新标题'
    assert db.snapshot()['records'][0]['data']['year'] == '2017'


def test_new_client_cannot_overwrite_or_delete_remote(tmp_path):
    db = LibraryDatabase(tmp_path / 'library.db')
    mid = movie_key(record()['nfo_path'])
    db.push([{'id': mid, 'base': None, 'data': record()}])
    assert db.push([])['accepted'] == []
    assert db.push([{'id': mid, 'base': None, 'data': record('错误')}])['conflicts']
    assert db.push([{'id': mid, 'base': None, 'deleted': True}])['conflicts']
    assert len(db.snapshot()['records']) == 1


def test_tombstone_and_restart(tmp_path):
    path = tmp_path / 'library.db'
    db = LibraryDatabase(path)
    mid = movie_key(record()['nfo_path'])
    db.push([{'id': mid, 'base': None, 'data': record()}])
    cursor = db.snapshot()['revision']
    db.push([{'id': mid, 'base': record(), 'deleted': True}])
    again = LibraryDatabase(path).snapshot(cursor)
    assert again['records'][0]['deleted']
    assert again['server_id'] == db.snapshot()['server_id']
