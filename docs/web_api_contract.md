# 网页版 API 契约

电影墙 Web 版的前后端接口规范。**前端与电影后端模块均以此文档为准**，任何改动需同步更新本文档。

## 1. 总体约定

- 独立的电影墙 FastAPI 服务：

  | 服务 | 路由前缀 | 默认端口 | 数据目录环境变量 |
  |---|---|---|---|
  | 电影墙 `movie_service` | `/api/movie` | 8010 | `MML_DATA_DIR`（默认仓库 `data/`） |

- Nginx 托管前端静态资源并把 `/api/movie/*` 反代到对应端口；Vite 开发服务器同样按此前缀代理。
- **筛选、排序、分组全部在前端完成**：列表接口一次性返回全部元数据（不含图片字节），前端常驻内存。
- 错误响应统一为 FastAPI 风格：`{"detail": "可读错误信息"}`，状态码 400/404/409/422/500。
- 时间戳为 Unix 秒（float）；路径为**服务器本地路径**（数据已由迁移脚本从 UNC 改写为挂载点）。
- 所有接口均为 JSON（图片接口除外），编码 UTF-8。

### 1.1 任务（Job）对象

长任务（扫描、刮削、榜单抓取、Excel 导入、Steam 补全、LLM 判定）统一走后台任务 + 前端轮询：

```json
{
  "id": "j_a1b2c3d4e5",
  "kind": "library.refresh",
  "status": "running",            // queued | running | done | error | cancelled
  "stage": "解析 NFO",             // 阶段名（可为空串）
  "current": 120, "total": 900,    // 进度（total 为 0 表示未知）
  "message": "正在处理 xxx.nfo",    // 最新一条日志/消息
  "error": null,                   // status=error 时的错误信息
  "result": null,                  // status=done 时的任务结果（各任务类型定义见下）
  "logs": ["..."],                 // 最多 300 条日志
  "created_at": 1764000000.0,
  "started_at": 1764000001.0,
  "finished_at": null
}
```

通用任务接口（两个服务都有）：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `{prefix}/jobs?kind=&limit=20` | 最近任务倒序（页面刷新后恢复进度条用） |
| GET | `{prefix}/jobs/{id}` | 单个任务详情 |
| POST | `{prefix}/jobs/{id}/cancel` | 请求协作式取消（长任务内 `ctx.check_cancelled()`） |

前端轮询建议：任务进行中每 800ms~1s 轮询一次，`status` 进入终态后停止。

### 1.2 图片接口约定

- 返回 `image/jpeg`，带 `ETag`/`Cache-Control: private, max-age=300`。
- 前端在"刷新海报/封面"后应追加 `?v=<时间戳>` 强制浏览器回源。
- 尺寸参数上限 1400px；非法参数返回 400。

---

## 2. 电影墙（/api/movie）

### 2.1 Movie DTO

`MovieListItem`（列表）与 `MovieDetail`（详情）字段一致，详情额外含完整简介与全部演员。**列表接口会把 `plot` 截断到 200 字符、`actors` 截断到 8 人**，详情不截断。

```json
{
  "id": "a1b2c3d4e5f6a7b8",        // sha1(normalize_path(nfo_path))[:16]，全局唯一
  "title": "电锯惊魂", "original_title": "Saw", "year": "2004",
  "premiered": "2004-10-29", "plot": "...", "tagline": "...",
  "runtime": "103", "file_size": "12.3 GB", "set_name": "",
  "genres": ["恐怖", "悬疑"], "countries": ["美国"], "tags": [],
  "rating": 8.5,                    // 主评分（豆瓣优先），0 表示无
  "rating_source": "douban",        // douban | imdb | tmdb | ""
  "ratings": {"douban": 8.5, "imdb": 8.4},   // NFO 中的各来源评分
  "user_rating": 0,                 // 用户评分 0-10（写入 NFO 的 rating name="user"），0=未评分
  "watched": false,                 // 以 WatchHistoryManager 为准
  "favorite": false,                // 以 FavoriteManager 为准
  "directors": ["詹姆斯·温"],
  "actors": [{"name": "...", "role": "...", "thumb": "..."}],
  "resolution": "1080p", "hdr_type": "", "video_codec": "x264", "audio_codec": "DTS",
  "imdb_id": "tt0387564", "tmdb_id": "", "douban_url": "",
  "video_path": "/mnt/movie/...", "nfo_path": "/mnt/movie/....nfo",
  "poster_path": "/mnt/movie/.../poster.jpg", "fanart_path": "",
  "added_time": 1700000000.0,
  "has_poster": true, "has_fanart": false,
  "rank": {"douban_top250": 12, "imdb_top250": null}   // 来自榜单缓存，无则 null
}
```

### 2.2 端点

| 方法 | 路径 | 请求 | 响应 | 说明 |
|---|---|---|---|---|
| GET | `/movies` | — | `{"total":1271,"movies":[MovieListItem…],"cache_info":{"timestamp":"…","movie_count":1271,"movie_paths":[…]}}` | 全量列表（元数据） |
| GET | `/movies/{id}` | — | `MovieDetail` | 404 if 不存在 |
| POST | `/movies/{id}/watched` | `{"watched":true}` | `MovieDetail` | 写 WatchHistoryManager + 缓存 |
| POST | `/movies/{id}/favorite` | `{"favorite":true}` | `MovieDetail` | 写 FavoriteManager + 缓存 |
| PUT | `/movies/{id}/rating` | `{"rating":8.5}` | `MovieDetail` | 0-10；写回 NFO `<ratings><rating name="user">`（复用 `NFOParser.update_user_rating`）并刷新缓存 |
| DELETE | `/movies/{id}` | — | `{"removed":true}` | **仅删本地记录**：缓存 + 观看历史 + 收藏；不动媒体文件 |
| POST | `/movies/{id}/reparse` | — | `MovieDetail` | 重新解析 NFO 更新缓存（右键「更新NFO」） |
| GET | `/movies/{id}/poster?w=200&h=300&mode=cover` | — | `image/jpeg` | mode: `cover`\|`contain`；源图缺失 404 |
| POST | `/movies/{id}/poster/invalidate` | — | `{"removed":N}` | 失效该海报的服务端缩略图缓存（右键「更新海报」） |
| GET | `/movies/{id}/nfo` | — | `{"xml":"…","path":"…"}` | 原始 NFO XML |
| PUT | `/movies/{id}/nfo` | `{"xml":"…"}` | `MovieDetail` | 校验可解析后写入并刷新缓存 |
| PUT | `/movies/{id}/fields` | 结构化字段（见 2.3） | `MovieDetail` | 「属性」编辑：等价于桌面版 NFO 编辑器保存逻辑 |
| POST | `/library/refresh` | `{"force":false}` | `{"job_id":"…"}` | 增量刷新（force=true 为全量重建）。kind=`library.refresh` |
| GET | `/library/info` | — | `{"cache_info":{…},"scanning":Job\|null,"paths_exist":[{"path":"…","exists":true}]}` | |
| GET | `/settings` | — | 见 2.4 | |
| PUT | `/settings` | 部分字段 | `{"saved":true}` | 改 `movie_paths` 后前端应触发 refresh |
| POST | `/scrape` | `{"ids":["…"]}` | `{"job_id":"…"}` | 豆瓣刮削批量任务，kind=`scrape.batch`。result: `{"succeeded":[id…],"failed":[{"id","message"}],"skipped":[id…]}` |
| GET | `/rankings/{kind}` | kind: `top250`\|`chart`\|`imdb_top250` | 见 2.5 | 用缓存 + 本地对比，同步快速 |
| POST | `/rankings/fetch` | `{"sources":["top250","chart","imdb_top250"],"use_cache":true}` | `{"job_id":"…"}` | kind=`rankings.fetch`；完成后前端再 GET |
| GET | `/newmovies/{kind}` | kind: `nowplaying`\|`coming` | 见 2.6 | |
| POST | `/newmovies/fetch` | `{"sources":["nowplaying","coming"],"use_cache":true}` | `{"job_id":"…"}` | kind=`newmovies.fetch` |
| GET | `/proxy/image?url=` | — | `image/jpeg` | 榜单/新片的外网海报代理；**host 白名单**（douban.com / imdb.com / tmdb.org / doubanio.com），白名单外 400 |
| GET | `/system/info` | — | `{"service":"movie","node":bool,"npx":bool,"data_dir":"…"}` | Node 可用性决定刮削功能是否可用 |
| GET | `/health` | — | `{"status":"ok",…}` | 工厂内置 |

**结果示例**

`library.refresh` 的 `result`：
```json
{"added": 5, "removed": 1, "unchanged": 1265, "total": 1271, "duration": 12.3}
```

`scrape.batch` 的 `result`：
```json
{"succeeded": ["id1"], "failed": [{"id": "id2", "message": "未匹配到豆瓣"}], "skipped": ["id3"]}
```

### 2.3 结构化字段编辑（PUT /movies/{id}/fields）

请求体为**部分字段**，仅提交要修改的键；实现需把它们写回 NFO（等价桌面版 NFO 编辑器），再重新解析刷新缓存：

```json
{
  "title": "…", "original_title": "…", "year": "…", "premiered": "…",
  "plot": "…", "tagline": "…", "runtime": "…",
  "genres": ["…"], "countries": ["…"], "tags": ["…"], "set_name": "…",
  "ratings": {"douban": 8.5, "imdb": 8.0},
  "directors": ["…"],
  "actors": [{"name": "…", "role": "…", "thumb": ""}],
  "uniqueids": {"imdb": "tt…", "tmdb": "…"},
  "fileinfo": {"resolution": "1080p", "hdr_type": "", "video_codec": "x264", "audio_codec": "DTS"}
}
```

### 2.4 设置（GET/PUT /settings）

```json
{
  "movie_paths": ["/mnt/movie", "/mnt/movie-series"],
  "blacklist_folders": ["Extras"],
  "blacklist_patterns": [".*[Ss]ample.*"],
  "poster_width": 200, "poster_height": 300,
  "grid_columns": 5, "poster_scale": 78
}
```
PUT 接受同结构的任意子集。

### 2.5 榜单（GET /rankings/{kind}）

```json
{
  "kind": "top250",
  "fetched_at": 1764000000.0,       // 榜单缓存时间，0=尚无缓存
  "items": [
    {"rank": 1, "title": "肖申克的救赎", "original_title": "…", "year": "1994",
     "rating": 9.7, "poster_url": "https://imgN.douban.com/…",
     "owned": true, "movie_id": "a1b2…", "in_library": true}
  ],
  "owned_count": 88, "missing_count": 162
}
```
`fetched_at=0` 时 `items=[]`，前端引导用户点「抓取榜单」。

### 2.6 新片（GET /newmovies/{kind}）

```json
{
  "kind": "nowplaying",
  "fetched_at": 1764000000.0,
  "items": [
    {"title": "…", "year": "2026", "genre": "…", "release_date": "…",
     "poster_url": "…", "douban_url": "…", "rating": 8.1,
     "in_library": true, "movie_id": "…"}
  ],
  "owned_count": 3, "missing_count": 27
}
```

---

## 4. 实现工程约定（后端）

### 3.5.0 完整网页刮削与展示扩展

网页“B站搜索”只用片名打开 `https://search.bilibili.com/pgc?keyword=...`。“B站播放”使用 `moviewall://bilibili/play?keyword=...&title=...&original_title=...&year=...`。自 3.6.3 起，匹配官方电影后查询正片分集，优先调用 `bilipc://page/player?type=ogv&epid=...&seasonId=...`。协议无法调用时打开同一分集的 `https://www.bilibili.com/bangumi/play/ep...` 网页播放器。暂无正片分集时打开官方电影页，无法确认匹配时打开影视搜索。无官方条目时仍可调用原有 BV、aid、cid 校验和播放流程。旧版只带 `keyword` 的链接和 `/search` 入口仍可识别。搜索和视频校验均在客户端执行。

3.5.2 共享协议的 Movie 资料增加可选 `video_width:int=0` / `video_height:int=0`，用于保留已核实像素尺寸；列表DTO继续通过resolution/hdr_type展示，不改变既有字段契约。0表示未知；不会把0×0判为SD。缺尺寸资料允许从规范视频文件名补全，旧缓存不重新扫描媒体目录。

3.5.1 新增 `GET /api/movie/movies/{id}/playlist.m3u8`：返回 UTF-8 播放列表附件（`application/vnd.apple.mpegurl`，`Cache-Control:no-store`，中文文件名使用 filename*）。无需 NAS 在 NUC 挂载，不读取或写入源文件，不改变观看状态；使用共享库记录中的原始 Windows/UNC 视频路径。不存在的影片404，路径缺失/不支持/含换行等400。用于浏览器未能唤起 moviewall 协议时由用户下载打开，协议启动仍要求本机已安装3.5.0或更新版。

以下接口均位于 `/api/movie/scrape`。除列表、设置读取和小体积配置写入外，网络/源文件操作返回 `{job_id}`，通过通用 jobs 接口查询结果。任务失败保留中文错误，凭据脱敏。

| 方法 | 路径 | 请求 / 结果 |
| --- | --- | --- |
| GET | `/workspace` | `{rows:[{id,movie_id,movie,is_new,status,poster_exists,subtitle_count,error_kind,error}]}`；恢复保存列表，不扫描 |
| POST | `/workspace/scan` | 显式扫描已配置媒体库，发现无 NFO 视频并更新快照 |
| GET/PUT | `/settings` | ScrapeSettings；GET 只返回 has_tmdb_api_key/has_tmdb_token/has_omdb_api_key，无原始密钥；PUT 空密钥保留 |
| POST | `/search` | `{source:tmdb或douban,query,year,page}` → 候选数组，每项含服务器 token |
| POST | `/preview` | `{target_id,candidate,previous?}` → 预览草稿；previous 必须为同一目标已确认会话 |
| POST | `/sessions/{session}/confirm` | `{title,plot,plot_source,poster_index:null或索引,rebuild_nfo}` → 已确认草稿 |
| POST | `/sessions/{session}/save` | `{selected_fields,overwrite,metadata_only,replace_identity_ack}` → 最新 MovieDetail |
| POST | `/edit/{target_id}` | 读取最新 NFO → `{session,movie,uniqueids,votes}` |
| POST | `/edit/sessions/{session}/save` | `{changes,votes?,poster_base64?}` → 最新 MovieDetail；只提交改变字段，图片上限10MB |

草稿含 session/target_id/fields/votes/artwork/warnings/confirmed/replace_identity/can_rebuild/plot_source/source_plots/sources/write_blocked/target_path。候选与草稿有效30分钟，最多1000项；过期需重新预览。服务器校验选片范围、NFO/海报路径、会话确认、身份替换、源版本、实际 NAS 写权限，并复用桌面备份/回滚。成功后更新 SQLite、共享海报和新增状态。扫描、确认、保存互斥，重复保存拒绝；批量由前端顺序提交已确认草稿，失败停止后续保存。

`POST /nas/connect` 增加 `read_only:bool=true`，明确 false 才切换可写；已存密码可留空复用，挂载中的登录身份变更仍需先断开。NAS 状态返回实际挂载权限；扫描或保存期间切换权限返回409。不会自动开放真实共享写入。

Movie DTO 的 genres 在显示层合并中英文同义项；rating/rating_source 优先有效豆瓣、IMDb、TMDB，ratings 原始数据不丢失。网页默认上映日期降序；固定三站评分显示顺序不依赖字典插入顺序。moviewall://play?path=完整视频路径 由3.5.0 Windows安装包注册，绝对路径/UNC 视频白名单，无 shell 执行。共享电影库无需为调用本机播放器挂载客户端视频到 NUC。

1. **导入顺序**：服务 `main.py` 第一时间初始化设置；任何模块**不得在导入期**创建 `CacheManager`/`ConfigManager`/`GameCacheManager` 等有状态对象，必须放在路由处理函数内或 `lifespan` 中（保证测试可用不同数据目录建多个 app 实例）。
2. **单例陷阱**：`ConfigManager` 是进程级单例。测试用 `tests/webapp/conftest.py` 的 `service_data_dir` 夹具（monkeypatch `utils.app_paths.DATA_DIR` + 重置单例），**严禁写真实 data/ 目录**。
3. **线程安全**：FastAPI 默认线程池并发处理请求，对缓存文件的读写必须加锁（进程内 `threading.Lock`）；保存 JSON 用「临时文件 + replace」原子写。
4. **复用优先**：领域逻辑一律复用仓库现有模块（`utils/`、`parsers/`、`scraper/`），服务层只做 HTTP 适配、任务编排、DTO 转换；禁止在服务层重写解析/抓取/分类逻辑。
5. **长任务**：一律走 `wall_common.jobs.JobManager`，`unique=True` 防重复提交（同一时刻同 kind 只跑一个），任务体内定期 `ctx.check_cancelled()`。
6. **图片**：一律走 `wall_common.images`（缩略图缓存、远程缓存、失效）。
7. **测试**：新增测试放 `tests/webapp/`，用 FastAPI `TestClient`；不得依赖真实 NAS/外网（网络调用 monkeypatch）；`pytest -q` 必须全绿。
8. **不改动桌面版行为**：允许给现有模块加**可选参数/提取纯函数**，但不得改变既有默认行为与签名语义。
# 3.4.0 共享电影库补充

## 3.4.1 NAS 设置与扫描

- GET `/nas`：`{available,connections,libraries,detail?}`，connection 包含 host/share/username/domain/port/vers、connected、mounted、read_only、has_password，不返回密码。
- POST `/nas/shares`：NASConfig（host、port=445、username、password、domain、share 可空、vers=3.0、guest=false），提交后台登录/共享列表任务，返回 job_id；完成结果 `{shares,message}`。
- POST `/nas/connect`：相同配置，share 必填；后台只读挂载，完成结果为公开 connection。已存账户密码留空复用；成功后密码仅存 NUC root 私有配置，接口不回传。
- POST `/nas/{id}/disconnect`：后台正常断开，不强制卸载；扫描/连接任务期间返回 409，原凭据保留供重新连接。
- GET `/nas/{id}/directories?path=相对路径`：返回 path 和 directories（name/path）；拒绝越出共享、绝对路径及符号链接逃逸。
- PUT `/nas/libraries`：`{libraries:[{connection_id,path}]}`，仅接受已连接共享中的目录，返回 `{saved,movie_paths}`。保存不扫描，NAS 密码不会进入 config.json 或同步记录。

`/system/info` 增加 nas_configured；source_available 在所选 NAS 连接均可用时为 true。扫描仍使用 `/library/refresh`，从物理挂载目录读取后转回原始 UNC 标识，保留范围外电影、已观看、个人评分与增量加入时间；不可达或读取中断保留共享库。NAS 海报复制到后端离线副本；NFO 重新读取和原始 XML GET 支持 NAS 路径映射。默认只读，未开放源文件编辑。

`/system/info` 另返回 nas_connected、nas_connected_count、nas_library_count，区分“共享连接成功”与“已配置扫描范围”。连接成功但未选择媒体库时，nas_connected=true、nas_library_count=0、source_available=false，前端提示选择媒体库，而不是“NAS 未挂载”。

评分校验修正：TMDB/IMDb/豆瓣/user 限定为 0–10；其他来源保留原始有限非负值，兼容 TMM 的烂番茄百分制，不将 91 错判非法。不合法记录的 422 提示包含电影与具体字段。

NUC 部署：`http://movie.nuc.local`，FastAPI 仅监听 `127.0.0.1:8010`。网页版和桌面同步使用同一个 `library.sqlite3`，不是两套独立缓存。

同步 ID 为 `sha1(ntpath.normpath(nfo_path).casefold())[:16]`；UNC 大小写、斜杠在 Windows/Linux 上结果相同。保留原始路径作为媒体标识，NAS 未挂载时不改写为虚构的 Linux 路径。

| 接口 | 行为 |
| --- | --- |
| GET `/api/movie/sync/changes?since=0` | 返回 `{server_id,revision,records:[{id,data,revision,deleted}]}`。以单事务快照的全局版本作为下一次游标；初次下载从 0 开始，墓碑也返回。 |
| POST `/api/movie/sync/push` | `{server_id,changes:[{id,base:null或完整原资料,data:变更字段,deleted:false}]}`。base 为空仅允许创建，不覆盖已有资料；按字段比较 base 与当前服务端，冲突字段保留服务端。返回 accepted、conflicts（id/fields/data）、revision、server_id。服务端实例不符返回 409。 |
| GET `/api/movie/sync/assets` | `{movie_id:sha256}` 海报清单。 |
| GET `/api/movie/sync/assets/{id}` | 后端海报副本，即使 NAS 离线仍可读取。 |
| PUT `/api/movie/sync/assets/{id}` | 原始图片字节，最大 8 MB/2500 万像素；验证图片并原子保存。更新已有海报需 If-Match=旧 sha256，冲突 409，保留原图。 |

`data` 是桌面 CacheManager 的完整电影字段，另加 `_favorite:bool`；`watched`、`ratings.user` 一并同步。拒绝配置/凭据等未知字段、无效类型、非有限数值/非法评分及不匹配的 NFO 标识。删记录需要 `deleted:true` 和完整 base，不接受无基线的全库覆盖。

桌面仅上传不应用服务端资料，仅下载只发 GET（包括海报），双向先上传变更再增量下载。缓存丢失不代表删除共享库：不从缺失记录自动推导墓碑，下载可从本机同步基线恢复；显式删除协议由调用方提交。电影墙原有“仅本地数据库”删除维持本机语义，下次下载可能重新出现；网页“从共享数据库删除”形成服务器墓碑并同步到其他客户端。均不删除媒体文件。

观看、收藏、个人评分修改产生新资料版本。个人评分没有可读 NAS NFO 时保存在共享库；NFO 可读时兼容原有写回。海报读取优先使用后端已保存副本。`/system/info` 新增 `sync:true` 与 `source_available:bool`，网页据此禁用源文件操作。NAS 挂载与完整源扫描/刮削编辑/播放按用户确认后续接入，本轮交付同步和浏览。

## 榜单发现接口（2026-11-17）

- `GET /discovery/series` → `{groups:[{name,source,items}]}`，一次读取全部本地系列及缓存片单。带 `?name=系列名` 时返回单一分组，未知系列返回 404。`source` 为 `tmdb` 或 `local`，成员按上映时间排序，包含 `title`、`original_title`、`year`、`premiered`、`rating`、`poster_url`、`plot`、`movie_id`、`tmdb_id`。未入库成员的 `movie_id` 为 `null`。单一分组在配置 TMDB 后可补取过期片单，失败时沿用 `series_collections/` 中已有缓存。
- 榜单与新片条目包含 `douban_id`、`douban_url` 和已缓存的 `plot`，榜单另返回 `premiered` 与 `rating_source`。无可用简介时 `plot` 为空。已核对同一影片 ID 的备用榜单海报可替换失效来源。已入库返回 `movie_id`，网页复用详情与本地播放。
- `GET /rankings/{kind}` 只读缓存。`fetched_at` 优先使用该来源独立时间戳，旧缓存没有独立时间戳时返回 0 并保留条目。独立时间戳用于判断该来源的缓存新鲜度。
- `POST /rankings/fetch` 单来源任务 kind 为 `rankings.fetch.来源`，多来源为 `rankings.fetch`。豆瓣 Top250 与 IMDb Top250 刷新时逐条补齐评分、简介和海报：优先使用已有缓存和本地库，其次读取豆瓣/IMDb 官方资料；无法核实的不覆盖已有成功值。豆瓣来源返回不完整 Top250 时保留上一次完整榜单，且不推进该来源的独立更新时间。任务结果含 `stale_sources` 与 `coverage`，来源空响应报错并保留旧缓存。
- `GET /discovery/annual/{year}` → `{year,fetched_at,source_url?,categories:[{id,title,items:RankingItem[]}]}`。无缓存返回空categories；只读，无隐式网络。年度必须已结束。
- `POST /discovery/annual/{year}/refresh` → `{job_id}`；官方页面动态发现新版page ID或旧版activity名，按年份独立缓存。网页开放已验证可用的2019年起年度；2018及更早官方接口当前不可用。来源不可用时报中文错误、保留原缓存。
- `POST /discovery/subject/{douban_id}` → `{job_id}`；任务结果为 `{title,plot,douban_id,fetched_at}`。网页榜单详情直接显示列表附带的简介，关闭详情后保留来源、筛选和滚动位置。
- 网页只在用户点击「刷新榜单」时提交豆瓣热门、正在上映和即将上映的更新任务。Top250 的缓存期限为一天，年度榜单为七天，过期后后台刷新。所有榜单均提供手动刷新和错误提示。
- `POST /discovery/series/refresh` → `{job_id}`；任务结果 `{updated,failed,settings_required,cached_posters,summary}`。按本地系列的 TMDB 锚点更新官方片单，中文站缺简介或海报时读取英文站补齐，已有评分和简介不被清空，并预存片单海报。未配置 TMDB 时只预存现有片单并返回 `settings_required:true`。多个锚点失败时保留上次片单；任务不修改电影库或 NAS/NFO。
- `GET /proxy/image?url=…&prefer_cache=true` 优先读取已有远程图片缓存，缺失时回源。图片代理仅允许现有来源白名单，使用唯一临时文件写入缓存。
