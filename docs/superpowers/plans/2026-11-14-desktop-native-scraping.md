# 桌面统一电影刮削 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 在桌面电影墙内发现、手动匹配并刮削新片，与现有豆瓣单片/批量补分共用数据源和安全写入。

**Architecture:** 纯 Python 领域模型连接视频发现、数据源提供者及 NFO/图片提交；Qt 工作台只调度后台任务、编辑草稿并展示结果。保持旧豆瓣公开门面及网页版调用兼容。参考已对照的 TMM 分层与人工匹配流程，不移植历史网络选择器。

**Tech Stack:** Python 3.10+（Windows 打包 3.11）、PyQt6、urllib、Pillow、pytest。

**Spec:** `docs/superpowers/specs/2026-11-14-desktop-native-movie-scraping-design.md`（用户已授权开始开发）。

## Global Constraints

- 仅 Windows / PyQt6 桌面版；不新增网页功能/API。
- 测试必须设置临时 `MML_DATA_DIR`，重置 ConfigManager；不操作真实影库。
- 领域模块不得导入 PyQt6；JSON/媒体写入使用临时文件与 `os.replace`。
- 三站评分独立；未知/无评分不伪造 0；评论数不得当作评分人数。
- 只把人工确认的匹配写盘；保留用户评分、观看、收藏、标签及未知 XML。
- 中文 Conventional Commits；提交本任务文件，不带入参考 Java 源码和原工作区图标/打包改动。

## Review Focus

1. 同目录两个视频，第二部不下载海报时不能误用第一部公共海报（Task 3 解析往返测试）。
2. 点击新候选后上一请求迟到，不能把旧详情写入当前草稿（Task 4 Qt 请求代际测试）。
3. 写图片成功而提交 NFO 失败时，旧文件要恢复（Task 3 异常注入）。
4. 无 TMDB/OMDb 凭据时仅豆瓣预设可运行；旧 API 结果结构不变（Task 5 回归）。
5. 新片无评分、候选重名或 NFO 损坏时不静默匹配/覆盖（Tasks 2/3/4）。

## Files and Interfaces

- `scraper/scrape_models.py`: `Candidate(source, id, title, original_title='', year='', overview='', poster_url='', media_type='movie')`; `Artwork(url, preview_url='', language='', width=0, height=0, source='tmdb')`; `Metadata(source, id, fields={}, ids={}, ratings={}, votes={}, artwork=[])`; `VideoTarget(video_path: Path, nfo_path: Path, title='', year='', existing=False, error='', nfo_stamp=None)`; `ScrapeDraft(target, fields={}, artwork=[], poster=None, confirmed=False, replace_identity=False, warnings=[], expected_files={})`。
- `scraper/scrape_settings.py`: `ScrapeSettings(tmdb_api_key='', tmdb_token='', omdb_api_key='', language='zh-CN', proxy='', timeout=20, douban_delay=1.5)`，`load()`/`save()`。
- `scraper/media_discovery.py`: `discover_videos(paths, blacklist_folders=(), blacklist_patterns=(), check_cancelled=None) -> list[VideoTarget]`; `guess_title_year(name) -> tuple[str,str]`。
- `scraper/metadata_sources.py`: `ProviderError`；`TmdbProvider(settings).search(query,year='',page=1)/details(candidate)`、`DoubanProvider(settings).search(...)/details(candidate)`、`OmdbProvider(settings).rating(imdb_id) -> tuple[float|None,int|None]`。返回共享 Candidate / Metadata；豆瓣重用 `douban_cli.run_douban_cli`，不引入循环导入。
- `scraper/scrape_http.py`: 有界 HTTPS JSON/图片传输、脱敏错误、可选代理；数据源模块内部使用。
- `scraper/scrape_service.py`: `ScrapeService(settings=None).search(source,query,year='',page=1)`、`.details(candidate)`、`.build_draft(target, metadata: Sequence[Metadata], plot_source='tmdb') -> ScrapeDraft`、`.save(draft, selected_fields=None, overwrite=False, metadata_only=False) -> Movie`、`.douban_only(target) -> dict`。save 拒绝未确认草稿；补分内部只接受可信/明确唯一的身份。
- `scraper/scrape_persistence.py`: XML 字段合并、备份/冲突检查/原子提交/回滚；复用 nfo_writer。
- `ui/scrape_tasks.py`: 一套后台任务 runner、进度、取消与生命周期；`ui/scrape_dialog.py`: `ScrapeDialog(movies=None, parent=None, mode='full', service=None)`，`saved = pyqtSignal(list)`（已写 NFO 路径）；`ui/scrape_settings_dialog.py`: 凭据/网络设置。
- `ui/main_window.py`: 工具栏及菜单进入同一工作台；保存后新增入库/刷新缓存与海报。
- `parsers/nfo_parser.py`: 本地显式图片关联、前缀优先与缺图语义；`scraper/douban_cli.py`: 兼容门面及统一写入。

## Task 1: 领域契约、配置与隔离基线

- [x] 写 `tests/scraping/conftest.py`、`test_settings.py`：临时目录隔离，配置原子保存、无凭据默认值。
- [x] 运行上述测试，确认新模块缺失造成 RED。
- [x] 实现共享 dataclass 与配置；更新 DESIGN.md 的桌面 Qt 所有权/交互约定。
- [x] 测试 GREEN；提交 `feat: 建立统一电影刮削模型与配置`。

## Task 2: 视频发现与数据源适配（可与持久化并行）

Consumes Task 1 模型/配置；Produces Files and Interfaces 中 discovery/providers。

- [x] 先写 `test_discovery.py`、`test_sources.py`，运行 RED。
- [x] 实现无 NFO 视频发现、名称推断、损坏 NFO、黑名单/碎片排除；保留 nfo_stamp。
- [x] 实现 TMDB 搜索/ID 定位/中文详情/图片、OMDb IMDb 评分、现有 CLI 的豆瓣完整候选与详情。无评分合法，独立来源错误可见。
- [x] 验证代理/超时/认证/限流/响应格式、来源 ID 及可取消发现；测试 GREEN 后提交。

## Task 3: 草稿、NFO 与图片安全提交

Consumes Task 1 模型和 Task 2 提供者；Produces ScrapeService 和 persistence。

- [x] 先写 `test_persistence.py` / `test_service.py`：新增往返、补缺与覆盖、未知节点/用户资料、三站评分、歧义身份、冲突/回滚、无海报多视频目录；运行 RED。
- [x] 实现 build_draft 与 save，显式确认、来源合并与旧身份替换预览、缺失不清空。
- [x] 图片 Pillow 验证并转 JPEG、有界下载、备份原子提交、失败回滚；解析器理解新本地 thumb 和旧兼容资产。
- [x] 测试 GREEN 后提交。

## Task 4: 统一桌面工作台及设置

Consumes 已冻结的 service/models 接口；界面可先用注入 service 做测试。

- [x] 先写 `test_scrape_dialog.py`：窗口构建、空状态、迟到响应、预设隔离、关闭/取消；运行 RED。
- [x] 使用原生 Qt 控件与既有 QSS，提供待处理列表、候选列表、详情草稿/字段选择、海报选图、简介来源、三项评分、队列保存与豆瓣批量模式。
- [x] 所有 I/O 后台执行、迟到响应失效、任务生命周期安全；设置掩码、连接测试、代理/超时。
- [x] 普通/小窗口截图检查，主按钮可达；GREEN 后提交。

## Task 5: 旧豆瓣与主窗口整合、完整回归

- [x] 写旧门面原子写入、保留 ID、歧义不写、评分人数正确及主窗口入口测试，运行 RED。
- [x] 保留公开函数签名与结果形状；旧豆瓣补分委托统一服务/持久化，不要求 TMDB/OMDb 凭据。工具栏/右键预设进入同一工作台，删除不再使用的重复调度。
- [x] 保存后新增电影入库、保留当前选中/观看信息、失效图片缓存；更新说明和打包依赖。
- [x] 临时 MML_DATA_DIR 下运行全量 pytest；编译检查新模块；静态 UI 审计与截图；可用的真实豆瓣联网验证，凭据不足的 TMDB/OMDb 如实记录。
- [x] 独立审阅完整改动，修复实际问题并回归；提交 `feat: 集成桌面统一刮削与豆瓣补全`。

## Execution record

- 隔离工作区：`C:/Users/king_/.codex/worktrees/desktop-native-scraping/Movie_Manager_Lite`，分支 `codex/desktop-native-scraping`。
- 基线：临时数据目录下 `pytest -q`，45 passed（1 条已有 Starlette 弃用警告）。
- 用户已明确“开始开发”，直接执行计划，不再增加一次计划审批。

- 实现提交：3dec9a4（模型配置）、b334a5b（安全保存）、f3e38c0（数据源）、fd1648e（豆瓣与入口）、87231f8（扫描及脱敏）、74d2cd2（兼容性与说明）、3c47796（Qt 工作台）。
- TDD 与回归：新增设置/发现/来源/持久化/服务/豆瓣兼容/主窗口/Qt 测试；最终阶段 213 passed，1 条基线已有 Starlette 弃用警告。
- 任务审阅已修复：同名翻拍年份、跨请求磁盘修改、快照同版本、默认不替换海报、背景图缺图语义、TMDB 评分别名及大小写、Windows junction 越界、同名扩展名冲突、未知编码 NFO、异常凭据脱敏、父子窗口线程关闭。
- 真实豆瓣端到端：公开电影 ID 1292052，通过 Qt 工作台搜索、预览、确认、选图、保存，主窗口后台读回新增 1 部电影；9.7 分、402 字简介、9623 字节 JPEG，NFO 对应视频正确。全部使用临时文件夹。
- 视图检查：1100×740 与 780×520，底部按钮可达；本次桌面源范围严格审计 0 findings。全项目审计仅发现既有网页 scrollbar 标准属性缺失，本次按用户要求不改网页版。
- 限制：TMDB/OMDb 已实现并有接口隔离测试，未获得真实用户凭据，联网验收尚未执行；没有宣称三站全部联网通过。
