// 电影墙 API 类型定义（对齐 docs/web_api_contract.md）

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

export interface NASConfig {
  host: string; port: number; username: string; password: string;
  domain: string; share: string; vers: string; guest: boolean;
}
export interface NASConnection extends Omit<NASConfig, 'password'> {
  id: string; connected: boolean; mounted: boolean; enabled: boolean;
  has_password: boolean; read_only: boolean; error: string;
}
export interface NASLibrary { connection_id: string; path: string; label?: string }
export interface NASStatus { available: boolean; connections: NASConnection[]; libraries: NASLibrary[]; detail?: string }
export interface NASDirectories { path: string; directories: { name: string; path: string }[] }

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
