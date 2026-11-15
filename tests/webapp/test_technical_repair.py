from pathlib import Path
import sqlite3

from utils.library_sync import LibraryDatabase, movie_key


def test_technical_repair_backs_up_and_preserves_other_fields(service_data_dir):
    from scripts.repair_technical_metadata import plan_repairs, apply_repairs
    folder=service_data_dir/'media'
    folder.mkdir()
    stem='Project.Hail.Mary.2026.2160p.DV.HDR'
    video=folder/(stem+'.mkv');video.write_bytes(b'video')
    nfo=folder/(stem+'.nfo')
    nfo.write_text('<movie><title>挽救计划</title><fileinfo><streamdetails><video><width>0</width><height>0</height></video></streamdetails></fileinfo></movie>',encoding='utf8')
    payload=nfo.read_bytes()
    database=LibraryDatabase(service_data_dir/'library.sqlite3')
    mid=movie_key(str(nfo))
    record={'nfo_path':str(nfo),'video_path':str(video),'title':'原始资料','resolution':'SD',
            'ratings':{'douban':8.6},'watched':True,'added_time':123,'_favorite':True}
    database.push([{'id':mid,'data':record}])
    plan=plan_repairs(service_data_dir)
    assert plan['checked']==1 and len(plan['changes'])==1
    assert plan['changes'][0]['data']['resolution']=='4K'
    # 核对期间的其他字段编辑必须保留。
    database.push([{'id':mid,'data':{'title':'同步期间的新标题'},'base':record}])
    result=apply_repairs(service_data_dir,plan)
    assert result['conflicts']==[]
    after=database.snapshot()['records'][0]['data']
    assert after['title']=='同步期间的新标题' and after['resolution']=='4K'
    assert after['ratings']==record['ratings'] and after['watched'] and after['_favorite'] and after['added_time']==123
    assert nfo.read_bytes()==payload and video.read_bytes()==b'video'
    assert Path(result['backup']).is_file()
    with sqlite3.connect(result['backup']) as backup:
        assert '"SD"' in backup.execute('SELECT data FROM movies WHERE id=?',(mid,)).fetchone()[0]
