# 网页版部署指南（Ubuntu · systemd + Nginx 裸机）

## 架构

```
浏览器
  │
  ▼
Nginx (80/443)
  ├── /              → 前端静态文件 (/var/www/media-wall)
  ├── /api/movie/*   → 反代 → 127.0.0.1:8010 (movie_service)
  └── /api/game/*    → 反代 → 127.0.0.1:8011 (game_service)
```

两个独立的 FastAPI 服务，各自有独立的数据目录，与桌面版"两个进程"的结构一致。

---

## 1. 系统依赖

```bash
# Python 3.10+
sudo apt update && sudo apt install -y python3 python3-venv python3-pip

# Node.js 18+（电影墙刮削功能需要 douban-cli）
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

# Nginx
sudo apt install -y nginx

# Pillow 系统依赖（图片处理）
sudo apt install -y libjpeg-dev zlib1g-dev
```

## 2. 获取代码

```bash
sudo mkdir -p /opt/media-wall
sudo chown $USER:$USER /opt/media-wall
cd /opt/media-wall
git clone <repo-url> .
```

## 3. Python 虚拟环境

```bash
python3 -m venv .venv
source .venv/bin/activate

# 桌面版依赖（openpyxl 等）
pip install -r requirements.txt

# 网页版服务端依赖
pip install -r webapp/backend/requirements.txt
```

## 4. 数据目录与 NAS 挂载

### 4.1 电影墙数据

```bash
sudo mkdir -p /var/lib/media-wall/movie
sudo chown $USER:$USER /var/lib/media-wall/movie
```

把桌面版 `data/` 目录里的 JSON 文件拷过来：

```bash
cp data/config.json /var/lib/media-wall/movie/
cp data/movie_cache.json /var/lib/media-wall/movie/
cp data/watch_history.json /var/lib/media-wall/movie/
cp data/favorites.json /var/lib/media-wall/movie/
cp data/failed_movies.json /var/lib/media-wall/movie/
# 榜单/新片缓存（可选）
cp data/douban_ranking_cache.json /var/lib/media-wall/movie/ 2>/dev/null || true
cp data/new_movie_cache.json /var/lib/media-wall/movie/ 2>/dev/null || true
```

### 4.2 游戏墙数据

```bash
sudo mkdir -p /var/lib/media-wall/game
sudo chown $USER:$USER /var/lib/media-wall/game
```

把桌面版 `%APPDATA%/LocalGameWall/data/` 里的文件拷过来：

```bash
cp /path/to/LocalGameWall/data/config.json /var/lib/media-wall/game/
cp /path/to/LocalGameWall/data/game_cache.json /var/lib/media-wall/game/
# 自定义封面目录（可选）
cp -r /path/to/LocalGameWall/data/posters /var/lib/media-wall/game/ 2>/dev/null || true
```

### 4.3 路径重映射

桌面版数据里的路径是 Windows UNC 格式（`//192.168.50.100/movie`、`\\192.168.50.100\movie`），需要改成 Ubuntu 上的挂载点。

假设 NAS 已挂载到 `/mnt/nas`：

```bash
# 电影墙 config.json
sed -i 's|//192.168.50.100/Movie Series|/mnt/nas/Movie Series|g' /var/lib/media-wall/movie/config.json
sed -i 's|//192.168.50.100/movie|/mnt/nas/movie|g' /var/lib/media-wall/movie/config.json
# 处理反斜杠格式
sed -i 's|\\\\192.168.50.100\\movie|/mnt/nas/movie|g' /var/lib/media-wall/movie/config.json
sed -i 's|\\\\192.168.50.100\\Movie Series|/mnt/nas/Movie Series|g' /var/lib/media-wall/movie/config.json

# movie_cache.json 里的 nfo_path / video_path / poster_path 同理
sed -i 's|//192.168.50.100/|/mnt/nas/|g' /var/lib/media-wall/movie/movie_cache.json
sed -i 's|\\\\192.168.50.100\\|/mnt/nas/|g' /var/lib/media-wall/movie/movie_cache.json

# watch_history / favorites 里的路径
sed -i 's|\\\\192.168.50.100\\|/mnt/nas/|g' /var/lib/media-wall/movie/watch_history.json
sed -i 's|//192.168.50.100/|/mnt/nas/|g' /var/lib/media-wall/movie/watch_history.json
sed -i 's|\\\\192.168.50.100\\|/mnt/nas/|g' /var/lib/media-wall/movie/favorites.json
sed -i 's|//192.168.50.100/|/mnt/nas/|g' /var/lib/media-wall/movie/favorites.json
```

> **提示**：也可以在首次启动后通过 Web 界面的设置页修改 `movie_paths`，然后触发刷新让服务端重新扫描（路径会自动更新到缓存中）。

### 4.4 游戏墙 Excel 路径

```bash
# game config.json 里的 excel_path 和 game_dirs
sed -i 's|C:\\Users[^"]*\\游戏清单\\.xlsx|/mnt/nas/游戏清单.xlsx|g' /var/lib/media-wall/game/config.json
```

## 5. 构建前端

```bash
cd webapp/frontend
npm install
npm run build
# 产物在 dist/
sudo mkdir -p /var/www/media-wall
sudo cp -r dist/* /var/www/media-wall/
sudo chown -R www-data:www-data /var/www/media-wall
```

## 6. systemd 服务

### 6.1 电影墙服务

```bash
sudo tee /etc/systemd/system/media-wall-movie.service << 'EOF'
[Unit]
Description=Media Wall - Movie Service
After=network.target

[Service]
Type=simple
User=media
Group=media
WorkingDirectory=/opt/media-wall
Environment=MML_DATA_DIR=/var/lib/media-wall/movie
Environment=PYTHONPATH=/opt/media-wall:/opt/media-wall/webapp/backend
Environment=MML_CORS_ORIGINS=https://media.example.com
ExecStart=/opt/media-wall/.venv/bin/uvicorn movie_service.main:app --host 127.0.0.1 --port 8010
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
```

### 6.2 游戏墙服务

```bash
sudo tee /etc/systemd/system/media-wall-game.service << 'EOF'
[Unit]
Description=Media Wall - Game Service
After=network.target

[Service]
Type=simple
User=media
Group=media
WorkingDirectory=/opt/media-wall
Environment=MML_DATA_DIR=/var/lib/media-wall/game
Environment=APP_DIR_NAME_OVERRIDE=LocalGameWall
Environment=PYTHONPATH=/opt/media-wall:/opt/media-wall/webapp/backend
Environment=MML_CORS_ORIGINS=https://media.example.com
ExecStart=/opt/media-wall/.venv/bin/uvicorn game_service.main:app --host 127.0.0.1 --port 8011
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
```

### 6.3 启动

```bash
sudo useradd -r -s /bin/false media 2>/dev/null || true
sudo chown -R media:media /var/lib/media-wall

sudo systemctl daemon-reload
sudo systemctl enable --now media-wall-movie
sudo systemctl enable --now media-wall-game

# 检查状态
sudo systemctl status media-wall-movie
sudo systemctl status media-wall-game
```

## 7. Nginx 配置

```bash
sudo tee /etc/nginx/sites-available/media-wall << 'EOF'
server {
    listen 80;
    server_name media.example.com;  # 改成你的域名或 IP

    # 前端静态文件
    root /var/www/media-wall;
    index index.html;

    # SPA 路由回退
    location / {
        try_files $uri $uri/ /index.html;
    }

    # 电影墙 API
    location /api/movie/ {
        proxy_pass http://127.0.0.1:8010;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        # 长任务可能需要较长时间
        proxy_read_timeout 300s;
    }

    # 游戏墙 API
    location /api/game/ {
        proxy_pass http://127.0.0.1:8011;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
    }

    # 图片缓存
    location ~* \.(jpg|jpeg|png|webp|svg|ico)$ {
        expires 30d;
        add_header Cache-Control "public, immutable";
    }
}
EOF

sudo ln -sf /etc/nginx/sites-available/media-wall /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### HTTPS（推荐）

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d media.example.com
```

## 8. 验证

```bash
# 健康检查
curl http://127.0.0.1:8010/api/movie/health
curl http://127.0.0.1:8011/api/game/health

# 通过 Nginx
curl http://localhost/api/movie/health
curl http://localhost/api/game/health

# 浏览器访问
open http://media.example.com
```

## 9. 日志

```bash
# 服务日志
sudo journalctl -u media-wall-movie -f
sudo journalctl -u media-wall-game -f

# Nginx 日志
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log
```

## 10. 更新

```bash
cd /opt/media-wall
git pull

# 更新依赖（如有变化）
source .venv/bin/activate
pip install -r requirements.txt -r webapp/backend/requirements.txt

# 重新构建前端
cd webapp/frontend
npm install
npm run build
sudo cp -r dist/* /var/www/media-wall/

# 重启服务
sudo systemctl restart media-wall-movie media-wall-game
```

## 11. 开发模式

前端开发服务器（热更新）：

```bash
cd webapp/frontend
npm run dev
# → http://localhost:5173
# Vite 自动代理 /api/movie → 8010, /api/game → 8011
```

后端开发模式：

```bash
# 终端 1：电影墙
cd /opt/media-wall
source .venv/bin/activate
MML_DATA_DIR=/var/lib/media-wall/movie \
PYTHONPATH=".:webapp/backend" \
uvicorn movie_service.main:app --reload --port 8010

# 终端 2：游戏墙
MML_DATA_DIR=/var/lib/media-wall/game \
APP_DIR_NAME_OVERRIDE=LocalGameWall \
PYTHONPATH=".:webapp/backend" \
uvicorn game_service.main:app --reload --port 8011
```
