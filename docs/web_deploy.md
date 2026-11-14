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
