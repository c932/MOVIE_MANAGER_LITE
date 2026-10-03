// API 客户端 — 封装 fetch，自动 JSON 解析 + 错误处理

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

async function request<T>(
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
    request<{ service: string; node: boolean; npx: boolean; data_dir: string }>(
      '/api/movie/system/info',
    ),
};

// ── 游戏墙 ────────────────────────────────────────────
export const gameApi = {
  ...jobsApi('/api/game'),
  list: () => request<GameListResponse>('/api/game/games'),
  detail: (key: string) =>
    request<GameListItem>(`/api/game/games/${encodeURIComponent(key)}`),
  update: (key: string, fields: Record<string, unknown>) =>
    request<GameListItem>(`/api/game/games/${encodeURIComponent(key)}`, {
      method: 'PUT',
      body: JSON.stringify(fields),
    }),
  setTier: (key: string, tier: Tier | null) =>
    request<GameListItem>(`/api/game/games/${encodeURIComponent(key)}/tier`, {
      method: 'PUT',
      body: JSON.stringify({ tier }),
    }),
  coverUrl: (key: string, w: number, h: number, variant = 'grid') =>
    `/api/game/games/${encodeURIComponent(key)}/cover?w=${w}&h=${h}&variant=${variant}`,
  refreshCover: (key: string, variant = 'grid') =>
    request<{ path: string }>(
      `/api/game/games/${encodeURIComponent(key)}/cover/refresh`,
      { method: 'POST', body: JSON.stringify({ variant }) },
    ),
  excelDiff: () =>
    request<{ job_id: string }>('/api/game/excel/diff', { method: 'POST' }),
  excelApply: () =>
    request<{ job_id: string }>('/api/game/excel/apply', { method: 'POST' }),
  enrich: (
    scope: 'all' | 'new' | 'selected',
    keys: string[] = [],
    options: { steam: boolean; ratings: boolean } = { steam: true, ratings: true },
  ) =>
    request<{ job_id: string }>('/api/game/enrich', {
      method: 'POST',
      body: JSON.stringify({ scope, keys, options }),
    }),
  llmClassify: (scope: 'all' | 'new' | 'selected', keys: string[] = []) =>
    request<{ job_id: string }>('/api/game/llm/classify', {
      method: 'POST',
      body: JSON.stringify({ scope, keys }),
    }),
  steamSearch: (q: string) =>
    request<{ results: { appid: number; name: string; definitive: boolean }[] }>(
      `/api/game/steam/search?q=${encodeURIComponent(q)}`,
    ),
  steamApply: (key: string, appid: number) =>
    request<GameListItem>(`/api/game/steam/apply`, {
      method: 'POST',
      body: JSON.stringify({ key, appid }),
    }),
  llmMatch: (key: string) =>
    request<{ game: GameListItem; appid: number; verified: boolean }>(
      '/api/game/llm/match',
      { method: 'POST', body: JSON.stringify({ key }) },
    ),
  llmPoster: (key: string) =>
    request<GameListItem>(`/api/game/llm/poster`, {
      method: 'POST',
      body: JSON.stringify({ key }),
    }),
  scanInstalled: () =>
    request<{ job_id: string }>('/api/game/scan-installed', {
      method: 'POST',
    }),
  settings: () => request<GameSettings>('/api/game/settings'),
  putSettings: (s: Partial<GameSettings>) =>
    request<{ saved: boolean }>('/api/game/settings', {
      method: 'PUT',
      body: JSON.stringify(s),
    }),
  systemInfo: () =>
    request<{ service: string; data_dir: string }>('/api/game/system/info'),
};

// re-export types for convenience
import type {
  Job, MovieListItem, MovieListResponse, LibraryInfo, MovieSettings,
  RankingResponse, NewMovieResponse, RankingItem, NewMovieItem,
  GameListItem, GameListResponse, GameSettings, Tier, TierSource,
  ExcelDiffResult, LlmVerdict, Actor, RankInfo,
} from '../types/api';
export type {
  Job, MovieListItem, MovieListResponse, LibraryInfo, MovieSettings,
  RankingResponse, NewMovieResponse, RankingItem, NewMovieItem,
  GameListItem, GameListResponse, GameSettings, Tier, TierSource,
  ExcelDiffResult, LlmVerdict, Actor, RankInfo,
};
