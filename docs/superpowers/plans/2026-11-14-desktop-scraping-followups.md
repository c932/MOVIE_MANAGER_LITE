# 桌面刮削扫描与 NFO 重建修正

用户要求：底部显示扫描进度和当前目录；使用原仓库指定新 ICO 打包；已有非 XML NFO 不能阻止搜索匹配后生成电影元数据。

只读检查发现真实《乐高蝙蝠侠大电影》NFO 以论坛图片 BBCode 开头，是发布说明而非 Kodi XML。当前统一“损坏且禁用”不适合这一输入。不能把读取失败、路径冲突与可备份替换的说明文件混为一谈。

## 实现与接口

- 扫描发出 `ScanProgress(stage, current, total, directory, found=0)`；遍历时未知总量，解析时使用已知视频数。Qt 底部持久进度条和可复制的完整目录，不通过主线程扫描。
- `VideoTarget.error_kind` / `error_detail` 区分 `not_metadata`、`invalid_xml`、`unreadable`、`path_conflict`，保持原 `error` 兼容。
- `can_rebuild_nfo(target)` 仅对可读取的非电影元数据/异常 XML 返回 True。`ScrapeDraft.rebuild_nfo` 默认 False，选择匹配本身不默许覆盖旧文件。
- 完整刮削模式增加“备份原 NFO 并重新生成”。勾选、确认匹配、保存确认后，以相同路径生成新 XML，并在替换前原样备份。不可读和路径冲突继续禁止保存；仅豆瓣补分不能重建完整电影元数据。
- 保留扫描/请求/保存版本检查、临时文件和原子替换、失败恢复。后台不自动写真实影库。
- 将 `E:/My_Code/Movie_Manager_Lite/Movie_Manager_Lite.ico` 原样同步到当前 worktree；EXE、安装图标及窗口图标统一使用此文件，发布资源中包含 ICO。

## 验证

先写针对发布说明、异常 XML、读取错误、用户取消、重建备份/回滚、进度回调和 Qt 底部进度的回归；设置临时 MML_DATA_DIR。运行全量 Python 测试、桌面 UI 审计与截图、Python 3.11 打包，并核对源 ICO 哈希及 EXE 的图标资源。

## 验收结果（2026-11-14）

- 全量 Python 测试 **263 passed**，1 条已有 Starlette/httpx 弃用提示；随后 MSI 构建默认版本调整为 3.2.2，相关构建测试 **9 passed**。所有测试使用临时 `MML_DATA_DIR`，Qt 使用 offscreen。
- 真实 NAS 上《乐高蝙蝠侠大电影》的 9005 字节发布说明 NFO 仅复制到临时目录验证。真实豆瓣搜索、预览、确认、下载海报及重建成功；备份与原始字节相同，NAS 原件 SHA256 前后相同。
- Qt 验证完整目录可复制、底部扫描进度可见；780×520 小窗口也保留底部进度。[界面截图](../../images/scraping-nfo-rebuild.png)。
- 独立审阅发现两项 P2：完整回滚后时间戳导致重试冲突、重建后界面草稿残留警告。均已补回归并修复：仅在恢复字节与原快照一致时刷新版本；界面同步快照、警告和重建选项，重试与再次保存通过。
- 新 ICO SHA256：`dccf38f5cc999a610bff373410d45a0b0c74246523130086ce3ff5155d8e52a7`。交付 EXE 的 9 个 RT_ICON 图像载荷与原 ICO 一致；MSI `Icon` 表和 `_internal/Movie_Manager_Lite.ico` 与原文件逐字节一致。
- Python 3.11 重新打包成功，交付 `dist/本地电影墙-3.2.2-win64.msi` 与 `dist/LocalMovieWall-3.2.2/LocalMovieWall.exe`，版本目录避免覆盖旧运行版。未安装到用户系统、未修改真实影库，继续保留当前 worktree 分支。
