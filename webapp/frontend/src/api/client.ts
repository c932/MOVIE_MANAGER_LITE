// API 客户端 — 封装 fetch，自动 JSON 解析 + 错误处理

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

export async function request<T>(
  url: string,
  options?: RequestInit,
): Promise<T> {
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  });

  if (res.status === 204) return undefined as T;

  const text = await res.text();
  let body: unknown;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    if (!res.ok) throw new ApiError(res.status, text || res.statusText);
    return text as unknown as T;
  }

  if (!res.ok) {
    const detail =
      typeof body === 'object' && body && 'detail' in body
        ? String((body as { detail: unknown }).detail)
        : res.statusText;
    throw new ApiError(res.status, detail);
  }

  return body as T;
}

// ── 通用任务接口 ──────────────────────────────────────
export const jobsApi = (prefix: string) => ({
  list: (kind?: string, limit = 20) =>
    request<{ jobs: Job[] }>(
      `${prefix}/jobs?${kind ? `kind=${kind}&` : ''}limit=${limit}`,
    ),
  get: (id: string) => request<Job>(`${prefix}/jobs/${id}`),
  cancel: (id: string) =>
    request<Job>(`${prefix}/jobs/${id}/cancel`, { method: 'POST' }),
});

// ── 电影墙 ────────────────────────────────────────────
export const movieApi = {
  playlistUrl: (id: string) => `/api/movie/movies/${id}/playlist.m3u8`,
  nasStatus: () => request<NASStatus>('/api/movie/nas'),
  nasShares: (config: NASConfig) => request<{job_id: string}>('/api/movie/nas/shares', {method: 'POST', body: JSON.stringify(config)}),
  nasConnect: (config: NASConfig) => request<{job_id: string}>('/api/movie/nas/connect', {method: 'POST', body: JSON.stringify(config)}),
  nasDisconnect: (id: string) => request<{job_id: string}>(`/api/movie/nas/${id}/disconnect`, {method: 'POST'}),
  nasDirectories: (id: string, path = '') => request<NASDirectories>(`/api/movie/nas/${id}/directories?path=${encodeURIComponent(path)}`),
  nasLibraries: (libraries: NASLibrary[]) => request<{saved: boolean; movie_paths: string[]}>('/api/movie/nas/libraries', {method: 'PUT', body: JSON.stringify({libraries})}),
  ...jobsApi('/api/movie'),
  list: () => request<MovieListResponse>('/api/movie/movies'),
  detail: (id: string) => request<MovieListItem>(`/api/movie/movies/${id}`),
  setWatched: (id: string, watched: boolean) =>
    request<MovieListItem>(`/api/movie/movies/${id}/watched`, {
      method: 'POST',
      body: JSON.stringify({ watched }),
    }),
  setFavorite: (id: string, favorite: boolean) =>
    request<MovieListItem>(`/api/movie/movies/${id}/favorite`, {
      method: 'POST',
      body: JSON.stringify({ favorite }),
    }),
  setRating: (id: string, rating: number) =>
    request<MovieListItem>(`/api/movie/movies/${id}/rating`, {
      method: 'PUT',
      body: JSON.stringify({ rating }),
    }),
  delete: (id: string) =>
    request<{ removed: boolean }>(`/api/movie/movies/${id}`, {
      method: 'DELETE',
    }),
  reparse: (id: string) =>
    request<MovieListItem>(`/api/movie/movies/${id}/reparse`, {
      method: 'POST',
    }),
  posterUrl: (id: string, w: number, h: number, mode = 'cover') =>
    `/api/movie/movies/${id}/poster?w=${w}&h=${h}&mode=${mode}`,
  invalidatePoster: (id: string) =>
    request<{ removed: number }>(
      `/api/movie/movies/${id}/poster/invalidate`,
      { method: 'POST' },
    ),
  getNfo: (id: string) =>
    request<{ xml: string; path: string }>(`/api/movie/movies/${id}/nfo`),
  putNfo: (id: string, xml: string) =>
    request<MovieListItem>(`/api/movie/movies/${id}/nfo`, {
      method: 'PUT',
      body: JSON.stringify({ xml }),
    }),
  putFields: (id: string, fields: Record<string, unknown>) =>
    request<MovieListItem>(`/api/movie/movies/${id}/fields`, {
      method: 'PUT',
      body: JSON.stringify(fields),
    }),
  refresh: (force = false) =>
    request<{ job_id: string }>('/api/movie/library/refresh', {
      method: 'POST',
      body: JSON.stringify({ force }),
    }),
  libraryInfo: () => request<LibraryInfo>('/api/movie/library/info'),
  settings: () => request<MovieSettings>('/api/movie/settings'),
  putSettings: (s: Partial<MovieSettings>) =>
    request<{ saved: boolean }>('/api/movie/settings', {
      method: 'PUT',
      body: JSON.stringify(s),
    }),
  scrape: (ids: string[]) =>
    request<{ job_id: string }>('/api/movie/scrape', {
      method: 'POST',
      body: JSON.stringify({ ids }),
    }),
  rankings: (kind: 'top250' | 'chart' | 'imdb_top250') =>
    request<RankingResponse>(`/api/movie/rankings/${kind}`),
  fetchRankings: (
    sources: string[],
    useCache = true,
  ) =>
    request<{ job_id: string }>('/api/movie/rankings/fetch', {
      method: 'POST',
      body: JSON.stringify({ sources, use_cache: useCache }),
    }),
  newMovies: (kind: 'nowplaying' | 'coming') =>
    request<NewMovieResponse>(`/api/movie/newmovies/${kind}`),
  fetchNewMovies: (sources: string[], useCache = true) =>
    request<{ job_id: string }>('/api/movie/newmovies/fetch', {
      method: 'POST',
      body: JSON.stringify({ sources, use_cache: useCache }),
    }),
  proxyImageUrl: (url: string) => `/api/movie/proxy/image?url=${encodeURIComponent(url)}`,
  systemInfo: () =>
    request<{ service: string; node: boolean; npx: boolean; data_dir: string; source_available: boolean; nas_connected: boolean; nas_configured: boolean; nas_library_count: number; sync: boolean }>(
      '/api/movie/system/info',
    ),
};

import type {
  NASConfig, NASStatus, NASLibrary, NASDirectories,
  Job, MovieListItem, MovieListResponse, LibraryInfo, MovieSettings,
  RankingResponse, NewMovieResponse, RankingItem, NewMovieItem, Actor, RankInfo,
} from '../types/api';
export type {
  Job, MovieListItem, MovieListResponse, LibraryInfo, MovieSettings,
  RankingResponse, NewMovieResponse, RankingItem, NewMovieItem, Actor, RankInfo,
};
