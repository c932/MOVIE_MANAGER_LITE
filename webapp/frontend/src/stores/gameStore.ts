// 游戏墙状态管理 — 列表数据 + 筛选/排序/搜索
import { create } from 'zustand';
import { gameApi } from '../api/client';
import type { GameListItem, GameListResponse, Tier } from '../types/api';

export type GameSortMode = 'update' | 'rating' | 'release' | 'name';

interface GameStore {
  games: GameListItem[];
  loading: boolean;
  error: string | null;
  cacheInfo: GameListResponse['cache_info'] | null;

  // 筛选
  search: string;
  selectedGenres: Set<string>;
  selectedTiers: Set<Tier>;
  selectedYears: Set<string>;
  selectedDevelopers: Set<string>;
  ratingBand: number; // 0=全部 50/75/90 -1=无评分
  installedOnly: boolean;

  // 排序
  sortMode: GameSortMode;
  posterScale: number;

  // 选中
  selectedKey: string | null;

  // 动作
  load: () => Promise<void>;
  setSearch: (s: string) => void;
  toggleGenre: (g: string) => void;
  toggleTier: (t: Tier) => void;
  toggleYear: (y: string) => void;
  toggleDeveloper: (d: string) => void;
  setRatingBand: (b: number) => void;
  setInstalledOnly: (v: boolean) => void;
  setSortMode: (m: GameSortMode) => void;
  setPosterScale: (s: number) => void;
  selectGame: (key: string | null) => void;
  updateGame: (game: GameListItem) => void;
  resetFilters: () => void;

  // 派生
  filtered: () => GameListItem[];
  filterOptions: () => {
    genres: string[];
    years: string[];
    developers: string[];
  };
}

export const TIER_COLORS: Record<Tier, string> = {
  '3A': 'bg-red-600 text-white',
  '2A': 'bg-orange-500 text-white',
  '精品小众': 'bg-purple-500 text-white',
  '普通游戏': 'bg-ink-600 text-ink-100',
  '避坑': 'bg-gray-600 text-gray-200',
};

export const TIER_LIST: Tier[] = ['3A', '2A', '精品小众', '普通游戏', '避坑'];

export const useGameStore = create<GameStore>((set, get) => ({
  games: [],
  loading: false,
  error: null,
  cacheInfo: null,

  search: '',
  selectedGenres: new Set(),
  selectedTiers: new Set(),
  selectedYears: new Set(),
  selectedDevelopers: new Set(),
  ratingBand: 0,
  installedOnly: false,
  sortMode: 'update',
  posterScale: 100,
  selectedKey: null,

  load: async () => {
    set({ loading: true, error: null });
    try {
      const data = await gameApi.list();
      set({ games: data.games, cacheInfo: data.cache_info, loading: false });
    } catch (e) {
      set({ error: (e as Error).message, loading: false });
    }
  },

  setSearch: (s) => set({ search: s }),
  toggleGenre: (g) =>
    set((s) => {
      const next = new Set(s.selectedGenres);
      next.has(g) ? next.delete(g) : next.add(g);
      return { selectedGenres: next };
    }),
  toggleTier: (t) =>
    set((s) => {
      const next = new Set(s.selectedTiers);
      next.has(t) ? next.delete(t) : next.add(t);
      return { selectedTiers: next };
    }),
  toggleYear: (y) =>
    set((s) => {
      const next = new Set(s.selectedYears);
      next.has(y) ? next.delete(y) : next.add(y);
      return { selectedYears: next };
    }),
  toggleDeveloper: (d) =>
    set((s) => {
      const next = new Set(s.selectedDevelopers);
      next.has(d) ? next.delete(d) : next.add(d);
      return { selectedDevelopers: next };
    }),
  setRatingBand: (b) => set({ ratingBand: b }),
  setInstalledOnly: (v) => set({ installedOnly: v }),
  setSortMode: (m) => set({ sortMode: m }),
  setPosterScale: (s) => set({ posterScale: s }),
  selectGame: (key) => set({ selectedKey: key }),

  updateGame: (game) =>
    set((s) => ({
      games: s.games.map((g) => (g.key === game.key ? game : g)),
    })),

  resetFilters: () =>
    set({
      search: '',
      selectedGenres: new Set(),
      selectedTiers: new Set(),
      selectedYears: new Set(),
      selectedDevelopers: new Set(),
      ratingBand: 0,
      installedOnly: false,
      sortMode: 'update',
    }),

  filtered: () => {
    const s = get();
    let result = s.games;

    if (s.search.trim()) {
      const q = s.search.toLowerCase().trim();
      result = result.filter(
        (g) =>
          g.title_cn.toLowerCase().includes(q) ||
          g.title_en.toLowerCase().includes(q) ||
          g.steam_name.toLowerCase().includes(q),
      );
    }
    if (s.selectedGenres.size > 0)
      result = result.filter((g) => g.genres.some((x) => s.selectedGenres.has(x)));
    if (s.selectedTiers.size > 0)
      result = result.filter((g) => s.selectedTiers.has(g.tier));
    if (s.selectedYears.size > 0)
      result = result.filter((g) => s.selectedYears.has(g.release_date.slice(0, 4)));
    if (s.selectedDevelopers.size > 0)
      result = result.filter((g) => s.selectedDevelopers.has(g.developer));
    if (s.ratingBand > 0)
      result = result.filter((g) => g.rating >= s.ratingBand);
    if (s.ratingBand === -1)
      result = result.filter((g) => g.rating === 0);
    if (s.installedOnly) result = result.filter((g) => g.installed);

    switch (s.sortMode) {
      case 'rating':
        result = [...result].sort((a, b) => b.rating - a.rating);
        break;
      case 'release':
        result = [...result].sort((a, b) => b.release_date.localeCompare(a.release_date));
        break;
      case 'name':
        result = [...result].sort((a, b) =>
          (a.title_cn || a.title_en).localeCompare(b.title_cn || b.title_en, 'zh'),
        );
        break;
      case 'update':
        result = [...result].sort((a, b) => b.update_date.localeCompare(a.update_date));
        break;
    }
    return result;
  },

  filterOptions: () => {
    const games = get().games;
    const genres = new Set<string>();
    const years = new Set<string>();
    const developers = new Set<string>();
    for (const g of games) {
      g.genres.forEach((x) => genres.add(x));
      if (g.release_date) years.add(g.release_date.slice(0, 4));
      if (g.developer) developers.add(g.developer);
    }
    return {
      genres: [...genres].sort(),
      years: [...years].sort().reverse(),
      developers: [...developers].sort(),
    };
  },
}));