# NUC 共享电影库 Implementation Plan

**Goal:** NUC 共享数据库、三种方向的桌面后台同步及 movie.nuc.local 网页浏览。
**Architecture:** SQLite 版本库 + FastAPI 同步接口 + Qt 后台客户端；React 使用同一 MovieStore。
**Tech Stack:** Python 3.11、SQLite、FastAPI、PyQt6、React、Caddy、systemd。
**Spec:** docs/superpowers/specs/2026-11-15-nuc-library-sync-design.md

## Global Constraints
- NAS 挂载由用户后续配置；本轮不改 NAS 文件。
- 同步默认关闭；冲突服务器优先；配置凭据不在同步资料内。
- 测试使用临时 MML_DATA_DIR，保持现有电影墙布局。

## Review Focus
- 新客户端空库不能触发全库删除；首次上传不能覆盖已有资料。
- 跨平台路径不能产生重复 ID；换服务端不能复用旧游标。
- 本机同步期间的新修改不能被下载覆盖。
- 仅下载不上传海报；仅上传不应用远程变更。
- NAS 不在线时依旧能够从服务器海报副本浏览。

## Tasks
- [x] 1. utils/library_sync.py：原子 JSON、稳定 ID、SQLite 版本库、按字段三方合并、删除墓碑；tests/sync/test_library_sync.py 验证冲突、删除、重启与路径。
- [x] 2. movie_service/routes_sync.py 与 MovieStore：change/push/assets 接口、共享资料持久化与海报副本；tests/webapp/test_library_sync_api.py 验证网页和同步互通。
- [x] 3. utils/sync_client.py、ui/library_sync_controller.py、SettingsDialog：三种方向、基线、后台同步、海报离线缓存、无重扫下载；tests/webapp/test_sync_client.py 与 Qt 集成测试。
- [x] 4. React 浏览体验：完整详情、系列、状态/评分/海报同步、设置与服务状态、源操作可用性。构建通过，lint 无错误（2 条原有 useJobPoll 警告），严格 UI 静态审计 0 发现。浏览器工具因无法确认 Windows 当前 URL 停止；页面与实际部署资源/海报 HTTP 已验证，浏览器交互验收仍未完成。
- [x] 5. NUC 部署脚本、初始只读导入、Caddy、systemd、两台 DNS 路由器仅新增 movie 域名；真实空客户端下载 1333 部/1332 图、上传 0、第二次下载 0。双客户端冲突与三种方向经临时服务测试，真实服务重启后数量/实例 ID 保持。
- [x] 6. 同步 API/部署文档、全量 485 pytest、前端 build/lint、3.4.0 MSI（包含 SQLite 和同步模块）、Git 中文提交。

交付限制：NAS 挂载与完整源扫描/刮削编辑/播放按用户明确选择后续接入；本轮不代安装桌面新版。初始本机仅有 1332 张可导出海报，剩余 1 部的源图后续 NAS 上线后补齐。
