# TMM 风格刮削管理页实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans，按下列任务连续实施。

**Goal:** 仅替换刮削入口，以表格管理、独立搜索刮削和独立编辑完成本地电影资料管理。
**Architecture:** 纯 Python 管理快照负责扫描与持久化；Qt 表模型负责排序过滤；现有 ScrapeService/TaskRunner 继续承担网络和安全保存。
**Tech Stack:** Python 3.11、PyQt6、现有 QSS、pytest、PyInstaller、MSI。
**Spec:** `docs/superpowers/specs/2026-11-15-tmm-scrape-manager-design.md`（用户已批准）

## Global Constraints

- 不改电影墙外观与业务；只替换其刮削入口的窗口类，保留 saved(list) 契约。
- 不自动扫描 NAS；所有媒体读写后台执行；未知状态不能伪装为不存在。
- 不新增视频探测依赖；字幕来自 NFO 和匹配的外挂文件。
- 测试隔离 MML_DATA_DIR；写盘备份、冲突检测、只读 NFO 替换与失败恢复沿用现有事务。

## Review Focus

- 排序/过滤/多选后操作的视频身份不变。
- 关闭、取消、快切影片期间不能有过期响应或后台线程被销毁。
- 旧队列、离线启动和首次无缓存启动均有明确状态。
- 编辑取消零写入，未知 XML/评分别名/技术参数保留。
- 刮削保存精确刷新列表和电影墙，不全库重扫。

## Task 1：管理快照与表模型

- [x] 在 `scraper/management.py` 定义 `ManagementRow`、扫描/合并/本机快照序列化及编辑载入保存服务。
- [x] 在 `ui/scrape_table.py` 定义表模型和筛选代理，覆盖全部所需列、数值排序与身份映射。
- [x] 先用 `tests/scraping/test_management.py`、`test_scrape_manager.py` 复现缺失接口，再实现并验证字幕、评分别名、新增/待补、离线恢复。
- [x] 提交中文 Conventional Commit。

## Task 2：表格主页与只读详情

- [x] 新建 `ui/scrape_manager.py`：顶部操作、搜索筛选、表格/详情分隔、底栏进度与目录；实现后台扫描、持久化、右键目录和选择恢复。
- [x] 新建 `ui/scrape_inspector.py`，只读显示电影资料与离线高清海报；异步载入且丢弃旧响应。
- [x] 管理窗口只接受当前电影列表及旧队列，重开不扫描；列宽与界面状态本机持久化。
- [x] 以 GUI 测试验证打开不扫描、扫描后状态、排序后选择、关闭等待、详情快切；提交。

## Task 3：独立搜索与编辑

- [x] 新建 `ui/scrape_search_dialog.py`，复用现有 ScrapeDialog 行为，重组为候选表格 + 海报详情 + 字段策略；仅处理选中电影，不读写全局队列。
- [x] 新建 `ui/metadata_editor.py`：后台载入 NFO、表单/评分/演员/文件标签、海报预览、字段差异与安全保存、取消零写入。
- [x] 管理主页连接两种对话框 saved 信号，后台精确更新行和缓存。
- [x] 新旧评分、手动编辑、冲突和取消测试；提交。

## Task 4：入口、视觉与交付

- [x] 仅切换 `MainWindow._show_scrape_workbench` 入口到新管理页，保留其他电影墙代码。
- [x] 在 `styles/style.qss` 为新窗口对象添加紧凑 TMM 风格；更新 DESIGN.md，不改变原电影墙主题。
- [x] 全量 pytest，截图检查 1366×768/1920×1080、100%/150% 缩放，检查真实数据副本和冻结模块。
- [x] 递增 MSI 版本、打包、验证并提交；不代为安装。

## 执行记录

- 2026-11-15：批准后开始；基线 `54d3cce`，已有工作区干净。

- 2026-11-15：任务1/2已提交 ffedf34、61cb74c；任务3及入口/主题已提交 71231e1。只有 MainWindow 刮削入口的窗口类替换，未改电影墙布局和排序。
- 通过原生 Qt 画面检查 1366×768、1920×1000、100%/150% 缩放；使用真实本地媒体缓存的临时副本生成 build/ui-review/ 下的管理、搜索、编辑截图，未写真实媒体库。列宽和数值排序重开恢复已实测。
- 新增测试覆盖真实 ScrapeService 搜索/确认/NFO保存/管理行刷新，以及取消零写入、冲突、回滚、关闭后刷新落盘、旧格式评分人数、旧系列清空、非豆瓣链接保留、多片简介来源和重复搜索结果选择。先复现审查缺陷后修复，最终全量 453 passed，1 条已有 Starlette/httpx 弃用提示。
- Python 3.11 构建 3.3.0 MSI 和独立目录，冻结包核实7个管理相关模块及最终审查修复；指定 ICO 的9张图标资源匹配。安装版当前为3.2.12，安装目录 D:\Program Files (x86)\LocalMovieWall\；未执行安装。
