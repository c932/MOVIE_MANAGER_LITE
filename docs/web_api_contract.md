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

1. **导入顺序**：服务 `main.py` 第一时间初始化设置；任何模块**不得在导入期**创建 `CacheManager`/`ConfigManager`/`GameCacheManager` 等有状态对象，必须放在路由处理函数内或 `lifespan` 中（保证测试可用不同数据目录建多个 app 实例）。
2. **单例陷阱**：`ConfigManager` 是进程级单例。测试用 `tests/webapp/conftest.py` 的 `service_data_dir` 夹具（monkeypatch `utils.app_paths.DATA_DIR` + 重置单例），**严禁写真实 data/ 目录**。
3. **线程安全**：FastAPI 默认线程池并发处理请求，对缓存文件的读写必须加锁（进程内 `threading.Lock`）；保存 JSON 用「临时文件 + replace」原子写。
4. **复用优先**：领域逻辑一律复用仓库现有模块（`utils/`、`parsers/`、`scraper/`），服务层只做 HTTP 适配、任务编排、DTO 转换；禁止在服务层重写解析/抓取/分类逻辑。
5. **长任务**：一律走 `wall_common.jobs.JobManager`，`unique=True` 防重复提交（同一时刻同 kind 只跑一个），任务体内定期 `ctx.check_cancelled()`。
6. **图片**：一律走 `wall_common.images`（缩略图缓存、远程缓存、失效）。
7. **测试**：新增测试放 `tests/webapp/`，用 FastAPI `TestClient`；不得依赖真实 NAS/外网（网络调用 monkeypatch）；`pytest -q` 必须全绿。
8. **不改动桌面版行为**：允许给现有模块加**可选参数/提取纯函数**，但不得改变既有默认行为与签名语义。
