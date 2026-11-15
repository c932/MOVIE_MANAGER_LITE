# Movie Manager Lite 网页版部署

后端端口 8010，接口前缀 `/api/movie`。前端为独立的 React 应用，根路由直接打开电影墙。

## Ubuntu

将本项目放到 `/opt/movie-wall`，创建 Python 虚拟环境，安装服务端依赖：

```bash
cd /opt/movie-wall
python3 -m venv .venv
.venv/bin/pip install -r webapp/backend/requirements.txt
cd webapp/frontend
npm ci
npm run build
```

独立的数据目录（例如 `/var/lib/movie-wall`）需要由服务账号可写。从桌面复制 config、缓存、封面，并将配置中的媒体目录/Excel 路径调整为服务器真实路径。

systemd 服务示例（将 User 改为部署账号）：

```ini
[Unit]
Description=Movie Manager Lite API
After=network-online.target

[Service]
User=media
WorkingDirectory=/opt/movie-wall
Environment=PYTHONPATH=/opt/movie-wall:/opt/movie-wall/webapp/backend
Environment=MML_DATA_DIR=/var/lib/movie-wall
ExecStart=/opt/movie-wall/.venv/bin/uvicorn movie_service.main:app --host 127.0.0.1 --port 8010
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Nginx 站点的 server 中加入：

```nginx
root /opt/movie-wall/webapp/frontend/dist;
location /api/movie/ {
    proxy_pass http://127.0.0.1:8010;
    proxy_read_timeout 120s;
}
location / {
    try_files $uri $uri/ /index.html;
}
```

验收：`curl http://127.0.0.1:8010/api/movie/health`，再通过前端访问列表与设置。

## Windows 开发

在项目根目录运行 `scripts/dev-web.bat`。前端默认端口 5173，仅代理 `/api/movie`；开发数据使用临时目录，避免改动真实库。
# NUC 实际部署（3.4.0）

- 地址：`http://movie.nuc.local` → `192.168.50.157`；.2 dnsmasq 与 .3 AdGuardHome 仅新增该域名解析，原配置各有 `movie-wall-时间戳.bak`。
- 代码：`/home/manfred/ai-local/services/movie-wall`，Python 3.11 独立 `.venv`。
- 数据：`/mnt/data/AI/movie-wall-data/library.sqlite3`；海报：同目录 `shared_posters/`。SQLite WAL 和版本库在重启后保留。JSON 仅用于兼容及已有缓存，不作为共享库事实来源。
- 网页：`/mnt/data/AI/movie-wall-web`，由 Caddy 提供；API 反代 `127.0.0.1:8010`。
- 服务：`/etc/systemd/system/movie-wall.service`，账号 manfred，已配置开机自动启动。查看：`systemctl status movie-wall`，日志：`journalctl -u movie-wall -n 60`。
- Caddy 站点模板：`deploy/movie-wall.caddy`。新增站点前备份 `/etc/caddy/Caddyfile.movie-wall-时间戳.bak`，验证成功才 reload。保留所有其他站点。

本轮经用户确认先上线同步与浏览，不挂载 NAS。当前导入已有桌面缓存 1333 部电影、1332 张海报；少 1 张是本机没有可导出的缓存，未访问 NAS 获取。没有导入 config.json、刮削 API Key 或 Cookie。网页扫描源 NFO/源文件编辑/播放要在后续挂载并配置路径后继续接入。

首次迁移工具：

```powershell
# 只读本机库与海报缓存，不扫描媒体目录
python scripts/shared_library_transfer.py export "$env:APPDATA/LocalMovieWall/data" "$env:TEMP/mml-initial-library.tar.gz"
```

```bash
# 在 NUC 停止应用后用于首次空库导入；已有记录只接受相同资料，不覆盖冲突
.venv/bin/python scripts/shared_library_transfer.py import /mnt/data/AI/movie-wall-data /tmp/mml-initial-library.tar.gz
```

后续更新：本机构建 `webapp/frontend`，上传明确的代码目录与 `dist`（不能覆盖运行数据），复制网页到 `/mnt/data/AI/movie-wall-web/` 后 `sudo systemctl restart movie-wall`。数据库备份使用 Python sqlite3 `Connection.backup()`，不要在服务运行时单独复制 SQLite 主文件而遗漏 WAL。

桌面用法：媒体库设置 → 开启后端数据库同步 → 地址 `http://movie.nuc.local` → 选择仅下载/仅上传/双向。新客户端建议先仅下载，确认本地电影和海报后改为双向。同步默认关闭；默认 120 秒自动同步，可手动立即同步，修改同步设置不会重扫 NAS。本机离线缓存继续可用。冲突报告在本机数据目录 `library_sync_report.json`。

真实只下载验收（必须指定独立测试目录，不使用真实桌面数据目录）：

```powershell
python scripts/verify_nuc_sync.py --url http://movie.nuc.local --data-dir "$env:TEMP/mml-nuc-download-verification-new"
```

观察结果：第一次 1333 部/1332 图、上传 0；第二次变更下载 0。另测试三种方向、双客户端冲突、显式删除和空库保护、重启持久化、非法数据拒绝、NAS 离线海报、下载重压缩不反复上传及同步期间保留本机编辑。浏览器自动化因无法确认 Windows 当前 URL 而停止，未完成浏览器交互验收；页面和示例海报的实际域名 HTTP 已验证。
