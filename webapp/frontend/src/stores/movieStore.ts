// 电影墙状态管理 — 列表数据 + 筛选/排序/搜索
import { create } from 'zustand';
import { movieApi } from '../api/client';
import type { MovieListItem, MovieListResponse } from '../types/api';

export type SortMode = 'default' | 'rating' | 'release' | 'added' | 'random';
export type WatchFilter = 0 | 1 | 2; // 0=全部 1=已看 2=未看
export type FavoriteFilter = 0 | 1; // 0=全部 1=已收藏

interface MovieStore {
  // 数据
  movies: MovieListItem[];
  loading: boolean;
  error: string | null;
  cacheInfo: MovieListResponse['cache_info'] | null;

  // 筛选状态
  search: string;
  searchDuplicate: boolean;
  selectedGenres: Set<string>;
  selectedCountries: Set<string>;
  selectedYears: Set<string>;
  selectedTags: Set<string>;
  minRating: number;
  watchFilter: WatchFilter;
  favoriteFilter: FavoriteFilter;
  sortMode: SortMode;
  posterScale: number;

  // 选中
  selectedId: string | null;

  // 动作
  load: () => Promise<void>;
  setSearch: (s: string) => void;
  toggleGenre: (g: string) => void;
  toggleCountry: (c: string) => void;
  toggleYear: (y: string) => void;
  toggleTag: (t: string) => void;
  setMinRating: (r: number) => void;
  setWatchFilter: (f: WatchFilter) => void;
  setFavoriteFilter: (f: FavoriteFilter) => void;
  setSortMode: (m: SortMode) => void;
  setPosterScale: (s: number) => void;
  setSearchDuplicate: (v: boolean) => void;
  selectMovie: (id: string | null) => void;
  updateMovie: (movie: MovieListItem) => void;
  removeMovie: (id: string) => void;
  resetFilters: () => void;

  // 派生
  filtered: () => MovieListItem[];
  filterOptions: () => {
    genres: string[];
    countries: string[];
    years: string[];
    tags: string[];
  };
}

export const useMovieStore = create<MovieStore>((set, get) => ({
  movies: [],
  loading: false,
  error: null,
  cacheInfo: null,

  search: '',
  searchDuplicate: false,
  selectedGenres: new Set(),
  selectedCountries: new Set(),
  selectedYears: new Set(),
  selectedTags: new Set(),
  minRating: 0,
  watchFilter: 0,
  favoriteFilter: 0,
  sortMode: 'default',
  posterScale: 78,
  selectedId: null,

  load: async () => {
    set({ loading: true, error: null });
    try {
      const data = await movieApi.list();
      set({
        movies: data.movies,
        cacheInfo: data.cache_info,
        loading: false,
      });
    } catch (e) {
      set({ error: (e as Error).message, loading: false });
    }
  },

  setSearch: (s) => set({ search: s }),
  setSearchDuplicate: (v) => set({ searchDuplicate: v }),
  toggleGenre: (g) =>
    set((s) => {
      const next = new Set(s.selectedGenres);
      next.has(g) ? next.delete(g) : next.add(g);
      return { selectedGenres: next };
    }),
  toggleCountry: (c) =>
    set((s) => {
      const next = new Set(s.selectedCountries);
      next.has(c) ? next.delete(c) : next.add(c);
      return { selectedCountries: next };
    }),
  toggleYear: (y) =>
    set((s) => {
      const next = new Set(s.selectedYears);
      next.has(y) ? next.delete(y) : next.add(y);
      return { selectedYears: next };
    }),
  toggleTag: (t) =>
    set((s) => {
      const next = new Set(s.selectedTags);
      next.has(t) ? next.delete(t) : next.add(t);
      return { selectedTags: next };
    }),
  setMinRating: (r) => set({ minRating: r }),
  setWatchFilter: (f) => set({ watchFilter: f }),
  setFavoriteFilter: (f) => set({ favoriteFilter: f }),
  setSortMode: (m) => set({ sortMode: m }),
  setPosterScale: (s) => set({ posterScale: s }),
  selectMovie: (id) => set({ selectedId: id }),

  updateMovie: (movie) =>
    set((s) => ({
      movies: s.movies.map((m) => (m.id === movie.id ? movie : m)),
    })),

  removeMovie: (id) =>
    set((s) => ({
      movies: s.movies.filter((m) => m.id !== id),
      selectedId: s.selectedId === id ? null : s.selectedId,
    })),

  resetFilters: () =>
    set({
      search: '',
      searchDuplicate: false,
      selectedGenres: new Set(),
      selectedCountries: new Set(),
      selectedYears: new Set(),
      selectedTags: new Set(),
      minRating: 0,
      watchFilter: 0,
      favoriteFilter: 0,
      sortMode: 'default',
    }),

  filtered: () => {
    const s = get();
    let result = s.movies;

    // 搜索（最高优先级）
    if (s.search.trim()) {
      const q = s.search.toLowerCase().trim();
      result = result.filter(
        (m) =>
          m.title.toLowerCase().includes(q) ||
          m.original_title.toLowerCase().includes(q) ||
          m.directors.some((d) => d.toLowerCase().includes(q)) ||
          m.actors.some((a) => a.name.toLowerCase().includes(q)),
      );
    }

    // 同名重复
    if (s.searchDuplicate) {
      const titleCount: Record<string, number> = {};
      for (const m of s.movies) {
        const key = m.title.toLowerCase();
        titleCount[key] = (titleCount[key] || 0) + 1;
      }
      result = result.filter((m) => titleCount[m.title.toLowerCase()] > 1);
    }

    // 类型（并集）
    if (s.selectedGenres.size > 0) {
      result = result.filter((m) =>
        m.genres.some((g) => s.selectedGenres.has(g)),
      );
    }
    // 国家
    if (s.selectedCountries.size > 0) {
      result = result.filter((m) =>
        m.countries.some((c) => s.selectedCountries.has(c)),
      );
    }
    // 年份
    if (s.selectedYears.size > 0) {
      result = result.filter((m) => s.selectedYears.has(m.year));
    }
    // 标签
    if (s.selectedTags.size > 0) {
      result = result.filter((m) => m.tags.some((t) => s.selectedTags.has(t)));
    }
    // 最低评分
    if (s.minRating > 0) {
      result = result.filter((m) => m.rating >= s.minRating);
    }
    // 观看状态
    if (s.watchFilter === 1) result = result.filter((m) => m.watched);
    else if (s.watchFilter === 2) result = result.filter((m) => !m.watched);
    // 收藏
    if (s.favoriteFilter === 1) result = result.filter((m) => m.favorite);

    // 排序
    switch (s.sortMode) {
      case 'rating':
        result = [...result].sort((a, b) => b.rating - a.rating);
        break;
      case 'release':
        result = [...result].sort(
          (a, b) => (b.premiered || b.year).localeCompare(a.premiered || a.year),
        );
        break;
      case 'added':
        result = [...result].sort((a, b) => b.added_time - a.added_time);
        break;
      case 'random':
        result = [...result].sort(() => Math.random() - 0.5);
        break;
    }

    return result;
  },

  filterOptions: () => {
    const movies = get().movies;
    const genres = new Set<string>();
    const countries = new Set<string>();
    const years = new Set<string>();
    const tags = new Set<string>();
    for (const m of movies) {
      m.genres.forEach((g) => genres.add(g));
      m.countries.forEach((c) => countries.add(c));
      if (m.year) years.add(m.year);
      m.tags.forEach((t) => tags.add(t));
    }
    return {
      genres: [...genres].sort(),
      countries: [...countries].sort(),
      years: [...years].sort().reverse(),
      tags: [...tags].sort(),
    };
  },
}));