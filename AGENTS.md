# AGENTS.md — Movie Manager Lite

## 项目概述

本地媒体库管理应用，包含两个独立程序：
- **电影墙**（`main.py`）：PyQt6 桌面应用，海报墙浏览 NFO 驱动的电影库
- **游戏墙**（`game_main.py`）：PyQt6 桌面应用，游戏封面墙 + Steam 补全 + LLM 五档分类

两个程序共享 `styles/`、`utils/`、`parsers/`、`models/`，但各有独立的数据目录和主窗口。

## 网页版（`webapp/`）

2026 年新增的网页版，后端 FastAPI（部署 Ubuntu），前端 React + Vite + Tailwind。

### 架构

```
webapp/
├── backend/
│   ├── wall_common/        # 共享基础设施（settings/jobs/images/factory/api）
│   ├── movie_service/      # 电影墙 FastAPI 服务（端口 8010，前缀 /api/movie）
│   │   ├── main.py         # 入口（create() 工厂函数）
│   │   ├── router.py       # 路由聚合
│   │   ├── routes_movies.py  # 电影 CRUD/NFO/海报
│   │   ├── routes_library.py # 扫描/刷新
│   │   ├── routes_fetch.py   # 刮削/榜单/新片
│   │   ├── store.py        # 数据存取层（每 app 一份，线程安全）
│   │   ├── scanner.py      # 非 Qt 版媒体库扫描
│   │   ├── tasks.py        # 后台任务体
│   │   └── deps.py         # 路由共享依赖
│   ├── game_service/       # 游戏墙 FastAPI 服务（端口 8011，前缀 /api/game）
│   │   ├── main.py / router.py / routes_games.py / routes_tasks.py / routes_settings.py
│   │   ├── store.py / tasks.py / scanner.py / covers.py / deps.py
│   │   └── ...
│   └── requirements.txt    # 网页版依赖（fastapi/uvicorn/pillow）
└── frontend/               # React + Vite + Tailwind + Zustand
    └── src/
        ├── api/client.ts   # API 客户端（fetch 封装）
        ├── types/api.ts    # TypeScript 类型定义（对齐契约）
        ├── stores/         # Zustand 状态管理（movieStore/gameStore）
        ├── components/     # UI 组件（movie/game 子目录）
        ├── pages/          # 页面（Home/MovieWall/GameWall）
        └── hooks/          # useJobPoll（后台任务进度轮询）
```

### 关键设计决策

1. **领域逻辑复用**：`models/`、`parsers/`、`utils/`、`gamewall/`、`scraper/` 是纯 Python，服务端直接导入复用；Qt 绑定的 UI 层（`ui/`）和 QThread workers 不复用，服务端重写编排层。
2. **Qt 解耦**：`scraper/` 原本在模块顶层导入 PyQt6，已把 Qt 线程类迁移到 `scraper/qt_tasks.py`，通过 `__getattr__` 懒加载保留原导入路径（`from scraper.douban_ranking import RankingFetcher` 仍有效）。
3. **数据目录**：`utils/app_paths.py` 新增 `MML_DATA_DIR` 环境变量支持；`wall_common/settings.py` 的 `resolve()` + `align_app_paths()` 负责服务端数据目录解析与单例对齐。
4. **单例陷阱**：`ConfigManager` 是进程级单例，测试用 `tests/webapp/conftest.py` 的 `service_data_dir` 夹具（monkeypatch DATA_DIR + 重置单例），**严禁写真实 data/ 目录**。
5. **后台任务**：`wall_common/jobs.py` 的 `JobManager` 替代 QThread，前端轮询 `GET /jobs/{id}` 获取进度。
6. **图片**：`wall_common/images.py` 用 Pillow 替代 QPixmap，缓存文件名带源图哈希前缀支持精确失效。

### API 契约

`docs/web_api_contract.md` 是前后端唯一权威，改动需同步更新。

### 部署

`docs/web_deploy.md`：Ubuntu systemd + Nginx 裸机部署指南。
`scripts/dev-web.bat`：Windows 本地开发一键启动（Vite + 两个后端）。

### 测试

```bash
.venv\Scripts\python.exe -m pytest -q   # 156 passed（含 77 个网页版测试）
```

网页版测试在 `tests/webapp/`，用 FastAPI TestClient + monkeypatch（不依赖外网/真实 NAS）。

## 桌面版

### 运行

```bash
pip install -r requirements.txt
python main.py        # 电影墙
python game_main.py   # 游戏墙
```

### 测试

```bash
pytest -q
```

### 数据目录

- 电影墙：`data/`（仓库根目录）
- 游戏墙：`%APPDATA%/LocalGameWall/data/`（通过 `APP_DIR_NAME_OVERRIDE` 环境变量区分）

### 编码规范

- Python 3.10+，类型注解
- 领域模块（`models/`、`parsers/`、`utils/`、`gamewall/`、`scraper/`）不得在导入期依赖 PyQt6
- UI 模块（`ui/`）可以自由使用 PyQt6
- JSON 写盘用临时文件 + `os.replace` 原子替换
- 中文错误信息，统一 `{"detail": "..."}` 格式
