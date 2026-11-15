"""从真实后端只下载到指定测试目录，不向服务器写数据。"""
from __future__ import annotations
import argparse
import io
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utils.sync_client import SyncClient, apply_patches


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://movie.nuc.local')
    parser.add_argument('--data-dir', type=Path, required=True)
    args = parser.parse_args()
    args.data_dir.mkdir(parents=True, exist_ok=True)
    from PIL import Image
    client = SyncClient(args.url, args.data_dir)
    def load(mid, path):
        candidate = args.data_dir / f'{mid}.jpg'
        return candidate.read_bytes() if candidate.is_file() else None
    def save(mid, path, payload):
        with Image.open(io.BytesIO(payload)) as image:
            image.verify()
        (args.data_dir / f'{mid}.jpg').write_bytes(payload)
    result = client.exchange({}, 'download', load_asset=load, save_asset=save,
                             progress=lambda message: print(message, flush=True))
    movies = apply_patches({}, result['patches'])
    assert not result['asset_errors'], result['asset_errors'][:3]
    client.commit(result)
    again = client.exchange(movies, 'download', load_asset=load, save_asset=save)
    assert not again['patches'] and not again['asset_downloaded'], '第二次同步应为增量空结果'
    print(json.dumps({'movies': len(movies), 'posters': len(list(args.data_dir.glob('*.jpg'))),
                      'uploaded': result['uploaded'], 'second_download': again['downloaded'],
                      'server_id': result['state']['server_id']}, ensure_ascii=False))
