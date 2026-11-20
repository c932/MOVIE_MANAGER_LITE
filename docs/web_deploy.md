# Movie Manager Lite 网页版部署

后端端口 8010，接口前缀 `/api/movie`。前端为独立的 React 应用，根路由直接打开电影墙。

## 3.6.3 哔哩哔哩入口

网页电影详情、榜单简介和右键菜单提供“B站搜索”“B站播放”。搜索直接打开 B 站「影视」分类，关键词只包含片名。Windows 电影墙 3.6.3 可以在 B 站客户端打开官方电影正片，客户端协议无法调用时，打开同一正片的网页播放器。没有官方条目时，经过校验的同名视频仍可通过 B 站客户端或网页打开。搜索、匹配和播放在用户设备上执行，账号权限由 B 站处理。

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

## 3.5.2 零尺寸误判与桌面闪窗

桌面图标组件构造时提前setVisible造成瞬时顶层窗，已删除该主动显示调用，回归覆盖“未加入布局不显示、加入可见父布局后正常显示”。Windows安装包升级至3.5.2，保留指定ICO与既有升级标识；不代安装。

《挽救计划》原NFO为width=0/height=0，旧解析器错误返回SD，图标又把泛SD显示为480P。现在无效尺寸按未知处理，缺项从文件名2160p/DV/HDR补全，实际正数尺寸仍优先，且保存在缓存。只含泛SD时不再套480P图标。该片真实视频经ffprobe只读核实为3840×2160，线上API已显示4K及Dolby Vision / HDR。

已核对共享库42条可疑既有记录并修正技术字段：4K 9部、1080p 32部、720p 1部，NFO均可读，0并发冲突。仅修改resolution/hdr_type/video_width/video_height；SQLite备份在 `/mnt/data/AI/movie-wall-data/backups/library-technical-20261115-194154-587182.sqlite3`，核对及执行报告分别为 `/tmp/mml-technical-audit-3.5.2.json` 和 `/tmp/mml-technical-applied-3.5.2.json`。NAS原文件保持原样。

修复命令默认仅核对，显式--apply才备份并更改共享库：

```bash
.venv/bin/python scripts/repair_technical_metadata.py /mnt/data/AI/movie-wall-data --report /tmp/technical-audit.json
.venv/bin/python scripts/repair_technical_metadata.py /mnt/data/AI/movie-wall-data --report /tmp/technical-applied.json --apply
```

本机同步设置仍为仅上传；保持用户同步方向。安装新版后读取已有缓存即可从明确文件名纠正旧SD标签，无需下载整库或扫描NAS。

## 3.5.1 网页滚动与播放修复

本轮只更新网页和API，Windows客户端3.5.0继续可用。海报墙虚拟渲染可见行，移除逐卡片和整墙背景模糊，详情以原生dialog加两帧后的 transform/opacity 过渡打开。客户端实测详情API约17–30ms，问题主要在1333张卡片与整墙重复渲染。

本机已安装的 moviewall 协议通过临时测试视频验收：注册URL实际创建 LocalMovieWall.exe 与 mpv.exe 新进程，原播放器进程保留。网页协议入口改为同步用户点击的独立目标，并在延后显示的可见帮助中提供播放列表附件和路径复制。`/movies/{id}/playlist.m3u8` 仅生成路径列表，不扫描或改动NAS；用户从下载栏打开即可交给本机播放器。

## 3.5.0 完整网页刮削与格式图标

网页增加全屏海报墙和浮动详情、默认上映日期倒序、类型中文归并、固定三站评分顺序；两端使用 logo/media-badges 同一套分辨率/HDR/Dolby Vision 资源。构建网页时 Vite 直接导入仓库根共享资源，部署 dist 即可。

顶部搜索&刮削打开 TMM 管理工作台，电影卡片右键直接搜索该片；管理列表恢复服务器快照，只有更新媒体库才扫描。搜索、预览、确认、保存和编辑复用桌面领域模块。NAS 默认只读；用户在 NAS 设置勾选“允许刮削写入 NFO 和海报”后，点击保存登录并连接共享切换为可写，才可保存。切换复用已保存密码，真实 NAS 不由部署脚本自动改为可写。

NUC 进程 PATH 包含 `/home/manfred/.nvm/versions/node/v24.21.0/bin`，供豆瓣 CLI 调用 Node/npx。首次 npx 使用可能下载固定版本包。刮削凭据使用独立 `MML_SCRAPE_CONFIG=/home/manfred/.config/localmoviewall/scrape_config.json`（目录0700、文件0600），由用户在网页刮削设置填写；不迁移桌面密钥或 NAS 密码。API返回配置存在标志，空密钥保留已有值。

Windows 3.5.0 MSI 注册 moviewall 播放协议，网页播放需要本机安装该版本及允许浏览器打开外部应用；视频由 Windows 默认播放器启动，本机必须能读取其 UNC 路径。手机/非 Windows 浏览器暂不支持该 Windows 播放桥。

验证写入仅使用 `scripts/nas_test_fixture.py` 创建的127.0.0.1:1445临时共享与 `/tmp/mml-nas-e2e-data` 副 API；`verify_nas_connection.py` 覆盖只读拒绝、可写切换、真实NFO备份/评分/UNC/观看/加入时间、外部改动冲突、恢复只读、断开后海报。结束移除测试连接并停止临时服务，真实NAS不写。

## 3.4.1 NAS 连接已上线

网页设置 → NAS 登录与媒体库：填写 IP（默认 192.168.50.100）、用户名和密码 → 测试登录并列出共享 → 选择或手动输入共享名 → 保存登录并连接共享 → 浏览子目录/添加共享根目录 → 保存媒体库目录 → 关闭设置 → 扫描 NAS。账号密码由用户在网页输入，本次不获取、不猜测真实 NAS 密码。

NUC 已安装 cifs-utils/smbclient。Root 所有的 `/usr/local/libexec/movie-wall-nas-helper.py` 由 `movie-wall-nas-helper.service` 开机启动，管理固定 `/mnt/movie-wall-nas/<id>` 只读挂载。Web 应用保留 NoNewPrivileges，通过 `/run/movie-wall-nas/control.sock` 调用白名单操作；目录 root:manfred 0750、socket 0660，持久凭据 `/var/lib/movie-wall-nas/connections.json` 为 root:root 0600。每次命令用临时 0600 凭据文件，执行后删除，不把密码放在命令行或回传。禁止任意挂载点、shell 命令和路径越界。NAS 版本默认 SMB 3.0，可选 3.1.1/2.1/2.0，不启用 SMB1。使用过的启用连接重启恢复。

部署助手：代码上传后执行 `sh deploy/install-nas-helper.sh`，再重启 movie-wall。服务不可用时 NAS 设置明确报错并允许刷新状态。更改用户名/密码前需正常断开已有连接。NAS 未连接仍可浏览共享数据库和已缓存海报；恢复连接后可扫描新 NFO，源编辑尚未开放。

真实验收使用 NUC 临时 SMB 服务，仅监听 127.0.0.1:1445，随机测试账户与独立 `/tmp/mml-nas-e2e-data`，从未使用真实 NAS 账户。已验证真实登录/共享列表、CIFS 只读挂载及拒绝写入、目录选择、UNC 身份稳定与范围外电影保留、NFO/海报读取、断开后海报及数据库保留。测试连接已移除、临时服务已停止；真实 NAS 等用户在网页填写密码后连接。浏览器工具仍无法确认 Windows 当前 URL，未完成自动点击交互验收。

用户已自行在网页连接真实 NAS：movie 与 Movie Series 均 connected=true；只读目录列表分别可读取 23/67 个文件夹。当前尚未保存媒体库目录，扫描按钮按设计保持禁用。状态栏已修复为“NAS 已连接 · 尚未选择并保存媒体库目录”；可分别点击“将整个共享加入媒体库”，再点“保存媒体库目录”，或先选择具体子目录。服务不会擅自选择根目录或启动全库扫描。

本次同步错误根因：TMM 的 tomatometerallcritics=91 被按十分制拒绝，现已按来源校验。服务器日志已看到原客户端后续 `/sync/push` 连续返回 200。既有客户端直接重试即可；另提供 3.4.1 MSI。

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

## 网页榜单更新（2026-11-17）

新增数据只写运行目录中的 `discovery/annual-年份.json` 与按条目缓存的简介；不扫描或修改NAS。年度来源为豆瓣官方页面的新旧两套数据接口，不需要迁移客户端密钥。网页已有电影使用本库详情及原播放机制，缺失电影仅提供简介与中创盘搜链接。

部署后验证实际域名bundle哈希、热门刷新完成时间、豆瓣海报图片200和有效图片字节、年度分类内容及简介任务。桌面安装包不受本次网页改动影响。NAS离线时本库详情仍可读共享缓存；播放依赖客户端能访问电影原路径。
