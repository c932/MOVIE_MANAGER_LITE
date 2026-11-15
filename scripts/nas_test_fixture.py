"""部署验收专用：只在 127.0.0.1:1445 提供临时测试目录，绝不访问真实 NAS。"""
from pathlib import Path
import json
import secrets


if __name__ == '__main__':
    from impacket import smbserver
    from impacket.ntlm import compute_lmhash, compute_nthash
    root = Path('/tmp/mml-smb-test')
    media = root / 'share' / 'Films' / 'TestFilm'
    media.mkdir(parents=True, exist_ok=True)
    (media / 'TestFilm.mkv').write_bytes(b'test-video-placeholder')
    (media / 'TestFilm.nfo').write_text('<movie><title>NAS只读扫描验收</title><year>2026</year><ratings>'
        '<rating name="tmdb"><value>7.5</value></rating></ratings></movie>', encoding='utf-8')
    private = root / 'test-login.json'
    if not private.exists():
        private.write_text(json.dumps({'host': '127.0.0.1', 'port': 1445, 'username': 'mml-test',
                                      'password': secrets.token_hex(16), 'share': 'MMLTest', 'vers': '2.0', 'guest': False}), encoding='utf-8')
        private.chmod(0o600)
    config = json.loads(private.read_text(encoding='utf-8'))
    server = smbserver.SimpleSMBServer(listenAddress='127.0.0.1', listenPort=1445)
    server.addShare('MMLTest', str(root / 'share'), 'Temporary movie-wall deployment verification')
    server.setSMB2Support(True)
    server.setLogFile(str(root / 'smb.log'))
    server.addCredential(config['username'], 0, compute_lmhash(config['password']), compute_nthash(config['password']))
    server.start()
