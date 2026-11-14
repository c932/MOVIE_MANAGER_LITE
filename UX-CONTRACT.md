# 桌面电影刮削交互约定

范围：本次新增的中文 Windows / PyQt6 工作流。网页版继续遵循其原有交互，本文件不要求改造网页。视觉与字体沿用 DESIGN.md 和 styles/style.qss。

## Canonical UI Map

| Capability | Canonical owner | Source of truth | Allowed variants | Verification |
| --- | --- | --- | --- | --- |
| Table Selection | ui/scrape_dialog.py：原生 QListWidget | 本文件、已确认的刮削设计 | 当前电影单选、Ctrl/Shift 多选已有电影补豆瓣 | tests/scraping/test_scrape_dialog.py |
| Select/Listbox | ui/scrape_dialog.py、ui/scrape_settings_dialog.py：原生 QComboBox | DESIGN.md | 接受 Windows 原生 popup 与键盘语义，按字段切换来源/模式 | tests/scraping/test_scrape_dialog.py |
| Form | ui/scrape_settings_dialog.py：QFormLayout；工作台字段编辑 | 本文件、ScrapeSettings.validate | 凭据掩码、显式保存、中文内联错误、保留输入 | tests/scraping/test_settings.py、test_scrape_dialog.py |
| Scrollbar | styles/style.qss：桌面 QScrollBar 与 QScrollArea | DESIGN.md | 正文内部滚动、底部主要操作固定可见 | 普通和小窗口 Qt 截图 |
| Toast | ui/scrape_dialog.py：持续状态文本；原生 QMessageBox | 本文件 | 常规结果内联、身份替换需确认、错误可重试 | tests/scraping/test_scrape_dialog.py |
| CRUD | scraper/scrape_service.py、scrape_persistence.py；ui/main_window.py 刷新队列 | 已确认的刮削设计 | 新片生成、已有补缺、明确覆盖、仅豆瓣补分 | tests/scraping/test_persistence.py、test_main_integration.py |

## 操作与状态

人工确认候选才可保存；搜索采用显式按钮/Enter 提交，输入法组字不触发远程搜索。搜索可清空，旧请求结果按代际隔离；切换目标不丢弃本窗口已确认草稿。新片、已有电影、仅豆瓣使用同一工作台，模式内草稿互不混写。

默认补缺保留已有海报与资料；明确选择覆盖及海报字段才能换图。仅豆瓣只写该来源评分及 ID/链接。无评分、缺少凭据或部分来源受限须显示真实状态，不禁用可独立使用的其他来源。

关闭有后台任务的窗口先协作取消后续任务，并等待当前操作结束；当前写盘不强制终止。身份变更确认默认选“不”。普通已确认草稿保存不重复弹确认。错误文本留在界面，允许重试；成功条目不因取消队列而撤销。

主窗口仅后台读回已保存条目并更新缓存；并发保存结果排队处理，不通过全库重扫清理观看或收藏记录。Qt 运行时测试与截图为界面证据，通用网页静态审计只能检查可识别的子集。

下载说明及可读取的异常 XML 允许用户选择“备份并重建”，人工确认候选后、保存前再次说明替换范围；默认不重建，取消无写入。无法读取或目标冲突不允许重建。扫描阶段/目录在底部持续可见，取消停止后续进度，旧任务不得覆盖新扫描显示。

扫描只由用户显式点击触发；打开工作台、重开应用和保存刮削设置只读取本机 `scrape_queue.json`。恢复不探测 NAS，已确认但未保存的候选不跨重启授权。扫描完成和保存成功后异步原子更新目标列表，连续变更合并并串行写入；取消/关闭不丢弃已开始的列表写入。右键菜单只对实际电影条目显示「打开所在文件夹」。

只读 NFO 的替换已获用户授权：先备份原字节，复核版本，再解除只读进行原子替换；成功后新 NFO 可写，失败恢复字节和原保护属性。备份失败、文件冲突均不得解除只读。权限/网络拒绝不伪装成功，海报只读继续拒绝。

评分补充由「确认匹配」触发，未确认候选不做跨站请求。补充失败可保存已取得资料；缺关联 ID 提供人工匹配 TMDB 的入口。新搜索/候选/目标使旧补充响应失效。IMDb 页面受限时使用官方免费评分数据集的本机 24 小时缓存，OMDb 为可选来源；准确区分 TMDB 与 IMDb 凭据。评分和票数分别以来源写入 NFO。

豆瓣资料确认后缺少 TMDB 关联时，自动发起 TMDB 原名/年份搜索并显示候选。唯一同名同年候选可直接预选和预览；多个或非精确候选项不得自动选择。预选不是确认，第二来源仍须用户点击「确认匹配」，之后才合并评分及系列字段。自动搜索失败时保留已确认豆瓣草稿并提供手动搜索。
