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
