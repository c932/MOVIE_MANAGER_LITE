import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, within, fireEvent, waitFor } from '@testing-library/react';
import MovieWall from '../pages/MovieWall';
import { movieApi } from '../api/client';
import { useMovieStore } from '../stores/movieStore';
import { preferredRating, localPlayUrl } from '../utils/movieDisplay';
import type { MovieListItem } from '../types/api';

vi.mock('../api/client', () => ({ movieApi: {
  list: vi.fn(), detail: vi.fn(), systemInfo: vi.fn(), posterUrl: (id: string) => '/poster/' + id,
} }));
const movie = (id: string, title: string, premiered: string) => ({id, title, original_title: '', year: premiered.slice(0,4), premiered,
  plot: '完整剧情', tagline: '', runtime: '120', file_size: '', set_name: '', genres: ['动作'], countries: ['美国'], tags: [],
  rating: 7, rating_source: 'douban', ratings: {tmdb: 9, imdb: 8, douban: 7}, user_rating: 0, watched: false, favorite: false,
  directors: [], actors: [], resolution: '4K', hdr_type: 'HDR', video_codec: '', audio_codec: '', imdb_id: '', tmdb_id: '', douban_url: '',
  video_path: '\\\\nas\\movie\\电影 ' + id + '.mkv', nfo_path: id + '.nfo', poster_path: id + '.jpg', fanart_path: '',
  added_time: 0, has_poster: true, has_fanart: false, rank: null} as MovieListItem);
const first = movie('a', '第一部', '2025-01-01');
const second = movie('b', '第二部', '2024-01-01');
beforeEach(() => {
  vi.clearAllMocks();
  useMovieStore.getState().resetFilters();
  useMovieStore.setState({movies: [], selectedId: null, loading: false, error: null});
  vi.mocked(movieApi.list).mockResolvedValue({movies: [second, first], total: 2, cache_info: {timestamp: '', movie_count: 2, movie_paths: []}});
  vi.mocked(movieApi.systemInfo).mockResolvedValue({source_available: false, nas_connected: false} as Awaited<ReturnType<typeof movieApi.systemInfo>>);
  vi.mocked(movieApi.detail).mockImplementation(async id => id === 'a' ? first : second);
});
describe('电影墙交互', () => {
  it('默认上映倒序，打开/关闭详情不重建网格或改变滚动', async () => {
    render(<MovieWall />);
    const scroll = screen.getByTestId('poster-scroll');
    const card = await within(scroll).findByRole('button', {name: /第一部/});
    expect(within(scroll).getAllByRole('button')[0]).toBe(card);
    scroll.scrollTop = 540;
    fireEvent.click(card);
    const dialog = await screen.findByRole('dialog', {name: '第一部'});
    expect(screen.getByTestId('poster-scroll')).toBe(scroll);
    expect(scroll.scrollTop).toBe(540);
    expect(within(scroll).getByRole('button', {name: /第一部/})).toBe(card);
    const logos = within(dialog).getAllByRole('img').filter(image => ['豆瓣','IMDb','TMDB'].includes(image.getAttribute('alt') || ''));
    expect(logos.map(image => image.getAttribute('alt'))).toEqual(['豆瓣','IMDb','TMDB']);
    fireEvent.click(dialog);
    await waitFor(() => expect(screen.queryByRole('dialog', {name: '第一部'})).not.toBeInTheDocument());
    expect(scroll.scrollTop).toBe(540);
  });
  it('全屏入口由点击触发，仍可退出', async () => {
    const request = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(document.documentElement, 'requestFullscreen', {configurable: true, value: request});
    render(<MovieWall />);
    fireEvent.click(screen.getByRole('button', {name: '全屏海报墙'}));
    expect(request).toHaveBeenCalledOnce();
    fireEvent.click(await screen.findByRole('button', {name: '退出全屏'}));
    expect(screen.getByRole('button', {name: '全屏海报墙'})).toBeInTheDocument();
  });
  it('评分优先豆瓣，无豆瓣用IMDb，播放链接保留完整UNC', () => {
    expect(preferredRating(first)).toEqual({source: 'douban', value: 7});
    expect(preferredRating({...first, ratings: {imdb: 8, tmdb: 9}}).source).toBe('imdb');
    expect(new URL(localPlayUrl(first)).searchParams.get('path')).toBe(first.video_path);
  });
});
