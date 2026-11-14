# IMDb 评分来源、源码参考与验证

参考本机旧版 tinyMediaManager：
`E:/My_Code/Movie_Manager_Lite/tinyMediaManager-master/src/org/tinymediamanager/scraper/imdb/ImdbMetadataProvider.java`。

- 125–132 行构造 `/title/{imdbId}/combined` 页面请求。
- 1031–1033 行通过 `CachedUrl` 下载并交给 Jsoup，属于直接抓 IMDb 页面，不依赖 OMDb。
- 215–235 行从旧 `tn15rating / starbar-meta / b` 提取评分；242–251 行从 `href="ratings"` 文本提取投票数。

该源码很老，旧 DOM 和 `/combined` 路由不能作为现代网页可用性证据。本实现独立编写，未复制 Java 代码：

- `ImdbProvider(settings).rating(tt_id)` 有界下载 `/title/{tt_id}/`，只读取 JSON-LD 根条目、根数组或 `@graph` 中显式绑定目标 IMDb URL 的标题，以及 `__NEXT_DATA__.props.pageProps` 下 `aboveTheFoldData` / `mainColumnData` 的同 ID 直接评分。
- 不遍历推荐、评论等任意嵌套评分；canonical 或 Next 主条目身份冲突时拒绝。评分必须有限、在 0–10 范围内且大于 0，并具备正整数票数。缺评分或无投票返回 `(None, None)`；不能核验身份、页面变更、网络错误抛中文 `ProviderError`。
- HTTP 202、403、网页连接失败/超时（HttpClient 无状态传输错误）或明确人机验证页面退回 IMDb 官方 `title.ratings.tsv.gz`，不尝试解决或绕过挑战。其他 HTTP 错误直接报告；身份错误和正常无评分不触发后备。
- `ImdbRatings(settings).rating(tt_id)` 可单独使用。缓存为应用数据目录 `imdb/title.ratings.tsv.gz`，遵循 `MML_DATA_DIR`，24 小时有效，跨实例/影片复用。缓存过期或损坏时重新下载；失败明确报错，不返回过期评分。官方无该 ID 时返回 `(None, None)`。
- 进程内最多保留 128 条最近查询（包含无条目结果），不是全表索引。每次先检查磁盘缓存有效期；文件路径、纳秒修改时间、大小、ttID 共同标识查询版本，文件更新后重新流式扫描。
- 压缩下载上限 32 MiB，解压上限 128 MiB，单行不超过 255 字节；流式扫描整份 gzip/TSV 到 EOF 校验 CRC、格式及目标重复身份，只返回精确匹配的 ttID。验证成功后以同目录临时文件、fsync、`os.replace` 原子更新缓存；不会将未验证下载写为有效缓存。进程内锁避免并行重复下载。

## 实际联网证据

2026-11-14 12:46 UTC（北京时间 20:46），通过现有 `HttpClient`、空白 `ScrapeSettings`（未加载任何用户配置或 key）、零重试只读请求：

- `https://www.imdb.com/title/tt0143145/` 返回 HTTP **202**，HttpClient 拒绝该非 200 响应。没有取得标题页，也没有读取其响应正文，因此不能声称现代页面解析已在线验证，亦不能仅凭状态码确定挑战正文内容。
- `https://datasets.imdbws.com/title.ratings.tsv.gz` 返回 HTTP **200**，下载 **8,753,316 字节**。表头为 `tconst\taverageRating\tnumVotes`；精确行 `tt0143145\t6.4\t223243`。
- 使用新实现对该真实下载进行整文件 gzip/TSV 校验后返回 `(6.4, 223243)`，约 2.6 秒。网页解析由离线 HTML 固定样例覆盖；数据集是每日快照，评分可能与实时网页不同。
- 将上述真实数据集放入全新的临时缓存目录后，再运行真实 `ImdbProvider.rating('tt0143145')`，网页请求触发官方缓存后备，返回 `(6.4, 223243)`；未再次下载数据集。

数据集说明及使用条件：<https://developer.imdb.com/non-commercial-datasets/>。官方免费数据集用于个人、非商业用途。

电影墙整合验证：真实豆瓣条目 `1293174`（《007之黑日危机》）提供原名、年份和 7.6 分，但 CLI 没有 IMDb ID，网页返回安全验证页。通过现有候选搜索并人工确认 TMDB `36643`，明确外部 ID 为 `tt0143145`，获得 TMDB `6.292`（3440 票）、IMDb `6.4`（223243 票）。三站评分写入临时 NFO 后原解析器成功读回；该路径没有配置 OMDb Key。

只读 NFO 的真实字节副本在备份后成功替换，备份逐字节一致；NAS 原件内容及属性保持原样。界面与列表恢复见 [验收截图](images/desktop-scraping-ratings.png)。
