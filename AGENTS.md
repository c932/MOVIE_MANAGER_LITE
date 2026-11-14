# AGENTS.md — Movie Manager Lite

本仓库为独立的电影墙项目，包含 PyQt6 桌面版与 FastAPI + React 网页版。

## 运行与测试

- 桌面入口：`main.py`；Python 3.10+，Windows 打包使用 Python 3.11。
- 后端：`webapp/backend/movie_service/`，端口 8010，API 前缀 `/api/movie`。
- 前端：`webapp/frontend/`，开发端口 5173。
- 测试：`.venv\Scripts\python.exe -m pytest -q`；前端 `npm run build`、`npm run lint`。
- 测试必须设置临时 `MML_DATA_DIR`；网页版使用 `service_data_dir` 夹具、重置 ConfigManager 单例，严禁写真实 data/。

## 数据与约定

- 源码默认数据目录：项目 `data/`；`MML_DATA_DIR` 可覆盖。安装版使用 `%APPDATA%/LocalMovieWall/data/`。
- Python 使用类型注解；服务端领域模块不得导入 PyQt6，Qt UI/worker 除外。
- JSON 写入使用临时文件 + `os.replace`；错误统一中文 `{"detail": "..."}`。
- API 契约以 `docs/web_api_contract.md` 为准，修改接口必须同步文档。
- 每轮修改后主动 `git add -A` 并提交，提交信息用中文 Conventional Commits。
- 游戏墙已于 2026-11-14 独立迁至 `E:\My_Code\Local_Game_wall`；两个项目不互相引用源码。
