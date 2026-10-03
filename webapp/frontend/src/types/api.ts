// 电影墙 / 游戏墙 API 类型定义（对齐 docs/web_api_contract.md）

// ── 通用 ──────────────────────────────────────────────
export type JobStatus = 'queued' | 'running' | 'done' | 'error' | 'cancelled';

export interface Job {
  id: string;
  kind: string;
  status: JobStatus;
  stage: string;
  current: number;
  total: number;
  message: string;
  error: string | null;
  result: unknown;
  logs: string[];
  created_at: number;
  started_at: number | null;
  finished_at: number | null;
}

// ── 电影墙 ────────────────────────────────────────────
export interface Actor {
  name: string;
  role: string;
  thumb: string;
}

export interface RankInfo {
  douban_top250: number | null;
  imdb_top250: number | null;
}

export interface MovieListItem {
  id: string;
  title: string;
  original_title: string;
  year: string;
  premiered: string;
  plot: string;
  tagline: string;
  runtime: string;
  file_size: string;
  set_name: string;
  genres: string[];
  countries: string[];
  tags: string[];
  rating: number;
  rating_source: string;
  ratings: Record<string, number>;
  user_rating: number;
  watched: boolean;
  favorite: boolean;
  directors: string[];
  actors: Actor[];
  resolution: string;
  hdr_type: string;
  video_codec: string;
  audio_codec: string;
  imdb_id: string;
  tmdb_id: string;
  douban_url: string;
  video_path: string;
  nfo_path: string;
  poster_path: string;
  fanart_path: string;
  added_time: number;
  has_poster: boolean;
  has_fanart: boolean;
  rank: RankInfo | null;
}

export interface MovieListResponse {
  total: number;
  movies: MovieListItem[];
  cache_info: {
    timestamp: string;
    movie_count: number;
    movie_paths: string[];
  };
}

export interface LibraryInfo {
  cache_info: { timestamp: string; movie_count: number; movie_paths: string[] } | null;
  scanning: Job | null;
  paths_exist: { path: string; exists: boolean }[];
}

export interface MovieSettings {
  movie_paths: string[];
  blacklist_folders: string[];
  blacklist_patterns: string[];
  poster_width: number;
  poster_height: number;
  grid_columns: number;
  poster_scale: number;
}

export interface RankingItem {
  rank: number;
  title: string;
  original_title: string;
  year: string;
  rating: number;
  poster_url: string;
  owned: boolean;
  movie_id: string | null;
  in_library: boolean;
}

export interface RankingResponse {
  kind: string;
  fetched_at: number;
  items: RankingItem[];
  owned_count: number;
  missing_count: number;
}

export interface NewMovieItem {
  title: string;
  year: string;
  genre: string;
  release_date: string;
  poster_url: string;
  douban_url: string;
  rating: number;
  in_library: boolean;
  movie_id: string | null;
}

export interface NewMovieResponse {
  kind: string;
  fetched_at: number;
  items: NewMovieItem[];
  owned_count: number;
  missing_count: number;
}

// ── 游戏墙 ────────────────────────────────────────────
export type Tier = '3A' | '2A' | '精品小众' | '普通游戏' | '避坑';
export type TierSource = 'manual' | 'llm' | 'excel' | 'rule';

export interface LlmVerdict {
  tier: Tier;
  is_aaa: boolean;
  confidence: number;
  score: number;
  reasoning: string;
}

export interface GameListItem {
  key: string;
  title_cn: string;
  title_en: string;
  raw_name: string;
  excel_row: number;
  quark_link: string;
  size_text: string;
  size_bytes: number;
  version: string;
  update_date: string;
  release_date: string;
  aaa_excel_marked: boolean;
  steam_appid: number;
  steam_name: string;
  developer: string;
  publishers: string[];
  platforms: string[];
  steam_categories: string[];
  genres: string[];
  description: string;
  steam_positive_pct: number;
  steam_review_total: number;
  metacritic: number;
  ign_score: number;
  gamersky_score: number;
  header_image: string;
  installed: boolean;
  installed_exe: string;
  installed_source: string;
  tier: Tier;
  is_aaa: boolean;
  tier_source: TierSource;
  aaa_score: number;
  aaa_tier: Tier;
  aaa_evidence: Record<string, unknown>;
  aaa_rule_version: string;
  aaa_manual_override: Tier | null;
  aaa_llm_verdict: LlmVerdict | null;
  rating: number;
  rating_source: string;
  has_cover: boolean;
  needs_enrichment: boolean;
}

export interface GameListResponse {
  total: number;
  games: GameListItem[];
  cache_info: { version: number; excel_mtime: number | null };
}

export interface GameSettings {
  excel_path: string;
  game_dirs: string[];
  poster_scale: number;
  network_enabled: boolean;
  enable_enrichment: boolean;
  enable_gamersky_scraper: boolean;
  enable_ign_scraper: boolean;
  llm_enabled: boolean;
  llm_base_url: string;
  llm_model: string;
  llm_api_key_set: boolean;
}

export interface ExcelDiffResult {
  added: string[];
  updated: string[];
  removed: string[];
  counts: { added: number; updated: number; removed: number };
  excel_meta: Record<string, unknown>;
  total?: number;
}
