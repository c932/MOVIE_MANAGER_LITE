"""Root 所有的只读 SMB 连接助手，仅通过受限 Unix socket 接受固定操作。"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import socket
import socketserver
import subprocess
import tempfile
import threading


class NASHelper:
    def __init__(self, state_dir='/var/lib/movie-wall-nas', mount_root='/mnt/movie-wall-nas',
                 runtime_dir='/run/movie-wall-nas', user='manfred'):
        self.state_dir, self.mount_root, self.runtime_dir = map(Path, (state_dir, mount_root, runtime_dir))
        import pwd
        account = pwd.getpwnam(user)
        self.uid, self.gid = account.pw_uid, account.pw_gid
        for path in (self.state_dir, self.mount_root, self.runtime_dir):
            path.mkdir(parents=True, exist_ok=True)
        self.state_dir.chmod(0o700)
        self.mount_root.chmod(0o755)
        self.runtime_dir.chmod(0o750)
        os.chown(self.runtime_dir, 0, self.gid)
        self.config = self.state_dir / 'connections.json'
        self.lock = threading.RLock()
        self.errors = {}

    def read(self):
        return json.loads(self.config.read_text(encoding='utf-8')) if self.config.exists() else {}

    def write(self, profiles):
        fd, name = tempfile.mkstemp(dir=self.state_dir)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(profiles, stream, ensure_ascii=False)
            os.chmod(name, 0o600)
            os.replace(name, self.config)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def spec(self, data, *, require_share=True):
        host, share = str(data.get('host', '')).strip(), str(data.get('share', '')).strip()
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.:-]{0,252}', host):
            raise ValueError('请输入有效 NAS IP 或主机名，不包含协议或路径')
        if (require_share and not share) or re.search(r'[/\\\x00-\x1f]', share) or len(share) > 100:
            raise ValueError('共享名无效，请选择 NAS 的 SMB 共享目录')
        port = int(data.get('port', 445))
        if not 1 <= port <= 65535:
            raise ValueError('SMB 端口应为 1–65535')
        spec = {key: str(data.get(key, '')) for key in ('username', 'domain')}
        if any(re.search(r'[\x00-\x1f]', value) for value in spec.values()):
            raise ValueError('登录名与域不能包含换行或控制字符')
        spec.update(host=host, share=share, port=port, guest=bool(data.get('guest', False)),
                    vers=str(data.get('vers', '3.0')), read_only=bool(data.get('read_only', True)))
        if spec['vers'] not in {'3.0', '3.1.1', '2.1', '2.0'}:
            raise ValueError('不支持此 SMB 版本')
        spec['id'] = hashlib.sha256(f'{host.casefold()}|{share.casefold()}|{port}'.encode()).hexdigest()[:16]
        existing = self.read()
        old = existing.get(spec['id']) or next((item for item in existing.values()
            if item['host'].casefold() == host.casefold() and item['username'] == spec['username']
            and item['domain'] == spec['domain']), {})
        password = data.get('password')
        if password in (None, ''):
            password = old.get('password', '') if old.get('username') == spec['username'] else ''
        if re.search(r'[\x00-\x1f]', str(password)):
            raise ValueError('密码不能包含换行或控制字符')
        if not spec['guest'] and (not spec['username'] or not password):
            raise ValueError('请输入 NAS 用户名和密码；已保存密码时可留空')
        spec['password'] = '' if spec['guest'] else str(password)
        spec['enabled'] = True
        return spec

    def target(self, mid):
        if not re.fullmatch(r'[a-f0-9]{16}', mid):
            raise ValueError('连接标识无效')
        path = self.mount_root / mid
        if path.parent.resolve() != self.mount_root.resolve() or (self.mount_flags(path) is None and path.is_symlink()):
            raise ValueError('挂载目录无效')
        return path

    def mount_flags(self, target):
        """从内核本地挂载表读取，不能 statvfs 离线 CIFS（会阻塞或 EINVAL）。"""
        try:
            for line in Path('/proc/self/mountinfo').read_text(encoding='utf-8').splitlines():
                fields = line.split()
                mountpoint = re.sub(r'\\([0-7]{3})', lambda match: chr(int(match[1], 8)), fields[4])
                if mountpoint == str(target):
                    return set(fields[5].split(','))
        except OSError:
            pass
        return None

    def command(self, args, password='', timeout=20):
        try:
            result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
        except FileNotFoundError as exc:
            raise ValueError('NUC 缺少 SMB 连接组件，请安装 cifs-utils 和 smbclient') from exc
        except subprocess.TimeoutExpired as exc:
            raise ValueError('NAS 连接超时，请检查地址、开机状态和 SMB 端口') from exc
        if result.returncode:
            message = (result.stderr or result.stdout or 'SMB 连接失败').strip()
            if password:
                message = message.replace(password, '***')
            raise ValueError('NAS 连接失败：' + message[:400])
        return result.stdout

    def credentials(self, spec):
        fd, name = tempfile.mkstemp(dir=self.runtime_dir, suffix='.cred')
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(f"username={spec['username'] if not spec['guest'] else 'guest'}\npassword={spec['password']}\ndomain={spec['domain']}\n")
        os.chmod(name, 0o600)
        return Path(name)

    def mount(self, spec):
        target = self.target(spec['id'])
        flags = self.mount_flags(target)
        if flags is not None:
            desired = spec.get('read_only', True)
            current = 'ro' in flags
            if current != desired:
                self.command(['/usr/bin/mount', '-o', f'remount,{"ro" if desired else "rw"},nosuid,nodev,noexec,soft', str(target)])
            return
        target.mkdir(exist_ok=True)
        credential = self.credentials(spec)
        try:
            options = (f'{"ro" if spec.get("read_only", True) else "rw"},nosuid,nodev,noexec,soft,vers={spec["vers"]},port={spec["port"]},'
                       f'uid={self.uid},gid={self.gid},dir_mode=0750,file_mode=0640,iocharset=utf8,'
                       f'credentials={credential}')
            self.command(['/sbin/mount.cifs', f'//{spec["host"]}/{spec["share"]}', str(target), '-o', options], spec['password'])
        finally:
            credential.unlink(missing_ok=True)

    def public(self, spec):
        flags = self.mount_flags(self.target(spec['id']))
        mounted = flags is not None
        reachable = False
        if mounted:
            try:
                with socket.create_connection((spec['host'], spec['port']), timeout=.5):
                    reachable = True
            except OSError:
                pass
        return {key: spec[key] for key in ('id', 'host', 'share', 'username', 'domain', 'port', 'guest', 'vers', 'enabled')} | {
            'connected': mounted and reachable, 'mounted': mounted, 'has_password': bool(spec['password']),
            'mount_path': str(self.target(spec['id'])),
            'read_only': 'ro' in flags if mounted else spec.get('read_only', True),
            'error': self.errors.get(spec['id'], '') if reachable else ('NAS 不可达或尚未连接' if mounted else self.errors.get(spec['id'], ''))}

    def handle(self, request):
        with self.lock:
            action = request.get('action')
            profiles = self.read()
            if action == 'status':
                return {'connections': [self.public(item) for item in profiles.values()]}
            if action == 'shares':
                spec = self.spec(request.get('config', {}), require_share=False)
                credential = self.credentials(spec)
                try:
                    output = self.command(['/usr/bin/smbclient', '-L', spec['host'], '-p', str(spec['port']),
                                           '-A', str(credential), '-g', '-m', 'SMB3'], spec['password'], timeout=15)
                finally:
                    credential.unlink(missing_ok=True)
                shares = [line.split('|')[1] for line in output.splitlines() if line.startswith('Disk|')]
                return {'shares': shares, 'message': '登录成功，请选择共享目录'}
            if action == 'connect':
                spec = self.spec(request.get('config', {}))
                old = profiles.get(spec['id'])
                if old and self.mount_flags(self.target(spec['id'])) is not None and any(old.get(key) != spec.get(key) for key in ('username', 'password', 'domain', 'guest', 'vers')):
                    raise ValueError('共享已连接，请先断开，再更换登录信息')
                self.mount(spec)
                profiles[spec['id']] = spec
                self.write(profiles)
                self.errors.pop(spec['id'], None)
                return self.public(spec)
            if action in {'disconnect', 'forget'}:
                mid = str(request.get('id', ''))
                target = self.target(mid)
                if mid not in profiles:
                    raise ValueError('NAS 连接不存在')
                if self.mount_flags(target) is not None:
                    self.command(['/usr/bin/umount', str(target)], timeout=15)
                if action == 'forget':
                    del profiles[mid]
                else:
                    profiles[mid]['enabled'] = False
                self.write(profiles)
                return {'disconnected': True}
            raise ValueError('不支持此 NAS 操作')

    def restore(self):
        with self.lock:
            for spec in self.read().values():
                if spec.get('enabled'):
                    try:
                        self.mount(spec)
                    except Exception as exc:
                        message = str(exc).replace(spec.get('password') or '\x00', '***')
                        self.errors[spec['id']] = message[:400]


def main():
    helper = NASHelper()
    path = helper.runtime_dir / 'control.sock'
    if path.exists():
        path.unlink()
    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            self.request.settimeout(35)
            try:
                line = self.rfile.readline(65537)
                if len(line) > 65536:
                    raise ValueError('请求过大')
                request = json.loads(line)
                result = {'ok': True, 'result': helper.handle(request)}
            except Exception as exc:
                message = str(exc)
                secret = locals().get('request', {}).get('config', {}).get('password', '')
                if secret:
                    message = message.replace(secret, '***')
                result = {'ok': False, 'detail': message[:500]}
            self.wfile.write(json.dumps(result, ensure_ascii=False).encode() + b'\n')
    class Server(socketserver.ThreadingUnixStreamServer):
        daemon_threads = True
    with Server(str(path), Handler) as server:
        path.chmod(0o660)
        os.chown(path, 0, helper.gid)
        threading.Thread(target=helper.restore, daemon=True).start()
        server.serve_forever()


if __name__ == '__main__':
    main()
