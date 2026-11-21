import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, within, fireEvent, waitFor } from '@testing-library/react';
import MovieWall from '../pages/MovieWall';
import { movieApi } from '../api/client';
import { useMovieStore } from '../stores/movieStore';
import { preferredRating, ratingForSource, localPlayUrl } from '../utils/movieDisplay';
import { LocalPlayback } from '../components/movie/LocalPlayback';
import type { MovieListItem } from '../types/api';

vi.mock('../api/client', () => ({ movieApi: {
  list: vi.fn(), detail: vi.fn(), series: vi.fn(), allSeries: vi.fn(), systemInfo: vi.fn(), posterUrl: (id: string) => '/poster/' + id,
  proxyImageUrl: (url: string) => '/proxy/' + encodeURIComponent(url),
  playlistUrl: (id: string) => '/api/movie/movies/'+id+'/playlist.m3u8',
  subtitleSearch: vi.fn(), subtitleDownload: vi.fn(), subtitleImport: vi.fn(), subtitleSave: vi.fn(), get: vi.fn(),
} }));
const movie = (id: string, title: string, premiered: string) => ({id, title, original_title: '', year: premiered.slice(0,4), premiered,
  plot: '完整剧情', tagline: '', runtime: '120', file_size: '', set_name: '', genres: ['动作'], countries: ['美国'], tags: [],
  rating: 7, rating_source: 'douban', ratings: {themoviedb: 9, imdb: 8, douban: 7}, user_rating: 0, watched: false, favorite: false,
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
  it('首页提供 PC 版安装包下载', () => {
    render(<MovieWall />);
    const link = screen.getByRole<HTMLAnchorElement>('link', {name: '下载 PC 版'});
    expect(link).toHaveAttribute('href', '/downloads/LocalMovieWall-3.7.0-win64.msi');
    expect(link).toHaveAttribute('download');
  });
  it('字幕来自已选候选，确认保存后更新海报卡语言', async () => {
    vi.mocked(movieApi.subtitleSearch).mockResolvedValue({
      items: [{source: 'subhd', id: 'a12', title: '第一部', release: 'First.2025.2160p', language: 'zh-Hans', page: 'https://subhdtw.com/a/a12', score: 100}],
      sources: [{source: 'subhd', name: 'SubHD', url: 'https://subhdtw.com/search/第一部', message: ''}],
    });
    vi.mocked(movieApi.subtitleDownload).mockResolvedValueOnce({
      verification_url: 'https://subhdtw.com/a/a12', message: '请完成网站验证',
    });
    vi.mocked(movieApi.subtitleImport).mockResolvedValue({token: 'preview', tracks: [{name: 'First.chs.srt', language: 'zh-Hans'}]});
    vi.mocked(movieApi.subtitleSave).mockResolvedValue({job_id: 'subtitle-job'});
    vi.mocked(movieApi.get).mockResolvedValue({status: 'done', result: {
      movie: {...first, subtitles: [{file: '第一部.srt', language: 'zh-Hans'}]}, saved_name: '第一部.srt',
    }} as Awaited<ReturnType<typeof movieApi.get>>);
    render(<MovieWall />);
    const intro = screen.getByTestId('movie-intro');
    fireEvent.click(await within(intro).findByRole('button', {name: '字幕'}));
    const dialog = screen.getByRole('dialog', {name: '第一部 · 字幕'});
    const panel = within(dialog);
    fireEvent.click(panel.getByRole('button', {name: '搜索'}));
    await panel.findByText('First.2025.2160p');
    fireEvent.click(panel.getByRole('button', {name: '下载'}));
    expect(await panel.findByRole('link', {name: '打开原站验证'})).toHaveAttribute('href', 'https://subhdtw.com/a/a12');
    const archive = new File(['字幕包'], 'subtitles.zip');
    fireEvent.change(panel.getByLabelText(/导入字幕/), {target: {files: [archive]}});
    const save = await panel.findByRole('button', {name: '保存到电影目录'});
    expect(movieApi.subtitleSave).not.toHaveBeenCalled();
    fireEvent.click(save);
    await panel.findByText('已保存 第一部.srt');
    expect(movieApi.subtitleSave).toHaveBeenCalledWith('a', 'preview', 0, 'zh-Hans');
    expect(within(screen.getByTestId('poster-scroll')).getByText('字幕 简中')).toBeInTheDocument();
  });
  it('1333部电影只渲染可见行，滚动和打开详情不创建整库卡片', async () => {
    const many = Array.from({length:1333},(_,i)=>({...first,id:'movie-'+i,title:'电影'+i}));
    vi.mocked(movieApi.list).mockResolvedValue({movies:many,total:1333,cache_info:{timestamp:'',movie_count:1333,movie_paths:[]}});
    vi.mocked(movieApi.detail).mockImplementation(async id=>many.find(movie=>movie.id===id)!);
    render(<MovieWall/>);
    const scroll=screen.getByTestId('poster-scroll');
    await within(scroll).findByRole('button',{name:/电影0/});
    expect(within(scroll).getAllByRole('button').length).toBeLessThan(100);
    expect(within(scroll).queryByRole('button',{name:/电影1332/})).not.toBeInTheDocument();
    scroll.scrollTop=12345;fireEvent.scroll(scroll);
    await waitFor(()=>expect(within(scroll).queryByRole('button',{name:/^电影0 /})).not.toBeInTheDocument());
    const card=within(scroll).getAllByRole('button')[0];
    fireEvent.click(screen.getByRole('button', {name: '海报墙'}));
    fireEvent.click(card);
    const dialog=await screen.findByRole('dialog');
    await waitFor(()=>expect(dialog).toHaveAttribute('data-phase','open'));
    expect(scroll.scrollTop).toBe(12345);
    expect(within(scroll).getAllByRole('button').length).toBeLessThan(100);
    fireEvent.click(dialog);
    expect(dialog).toHaveAttribute('data-phase','closing');
    await waitFor(()=>expect(dialog).not.toBeInTheDocument());
    expect(scroll.scrollTop).toBe(12345);
  });
  it('默认上映倒序，打开/关闭详情不重建网格或改变滚动', async () => {
    render(<MovieWall />);
    const scroll = screen.getByTestId('poster-scroll');
    const card = await within(scroll).findByRole('button', {name: /第一部/});
    expect(within(scroll).getAllByRole('button')[0]).toBe(card);
    scroll.scrollTop = 540;
    fireEvent.click(screen.getByRole('button', {name: '海报墙'}));
    fireEvent.click(card);
    const dialog = await screen.findByRole('dialog', {name: '第一部'});
    expect(screen.getByTestId('poster-scroll')).toBe(scroll);
    expect(scroll.scrollTop).toBe(540);
    expect(within(scroll).getByRole('button', {name: /第一部/})).toBe(card);
    const logos = within(dialog).getAllByRole('img').filter(image => ['豆瓣','IMDb','TMDB'].includes(image.getAttribute('alt') || ''));
    expect(logos.map(image => image.getAttribute('alt'))).toEqual(['豆瓣','IMDb','TMDB']);
    expect(logos[2].parentElement).toHaveTextContent('9.0');
    const searchLink = within(dialog).getByRole<HTMLAnchorElement>('link', {name: 'B站搜索'});
    expect(searchLink.querySelector('.bilibili-icon')).toHaveAttribute('aria-hidden', 'true');
    const search = new URL(searchLink.href);
    expect(search.origin).toBe('https://search.bilibili.com');
    expect(search.pathname).toBe('/pgc');
    expect([...search.searchParams.entries()]).toEqual([['keyword', '第一部']]);
    const play = new URL(within(dialog).getByRole<HTMLAnchorElement>('link', {name: 'B站播放'}).href);
    expect(play.href).toMatch(/^moviewall:\/\/bilibili\/play\?/);
    expect(play.searchParams.get('title')).toBe('第一部');
    expect(play.searchParams.get('year')).toBe('2025');
    expect(play.searchParams.get('keyword')).toBe('第一部');
    expect(play.searchParams.get('fallback')).toBe(search.href);
    fireEvent.click(dialog);
    await waitFor(() => expect(screen.queryByRole('dialog', {name: '第一部'})).not.toBeInTheDocument());
    expect(scroll.scrollTop).toBe(540);
  });
  it('正常模式顶部显示简介，海报墙与全屏模式按层级收起并统一使用浮窗', async () => {
    const request = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(document.documentElement, 'requestFullscreen', {configurable: true, value: request});
    render(<MovieWall />);
    const intro = screen.getByTestId('movie-intro');
    const filters = screen.getByTestId('filter-sidebar');
    await waitFor(() => expect(within(intro).getByText('第一部')).toBeInTheDocument());
    expect(intro).toHaveAttribute('data-visible', 'true');
    expect(filters).toHaveAttribute('data-visible', 'true');

    const wall = screen.getByTestId('poster-scroll');
    fireEvent.click(within(wall).getByRole('button', {name: /第二部/}));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    await waitFor(() => expect(within(intro).getByText('第二部')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', {name: '海报墙'}));
    expect(intro).toHaveAttribute('data-visible', 'false');
    expect(filters).toHaveAttribute('data-visible', 'true');
    fireEvent.click(screen.getByRole('button', {name: '全屏海报墙'}));
    await waitFor(() => expect(filters).toHaveAttribute('data-visible', 'false'));
    expect(request).toHaveBeenCalledOnce();
    expect(screen.getByRole('button', {name: '退出全屏'})).toBeInTheDocument();
  });
  it('系列卡片补齐缺失电影，详情切换同系列影片后返回原位置', async () => {
    const name = '测试系列';
    const members = [first, second].map(movie => ({...movie, set_name: name}));
    const result = await movieApi.list();
    vi.mocked(movieApi.list).mockResolvedValue({...result, movies: members});
    vi.mocked(movieApi.detail).mockImplementation(async id => members.find(movie => movie.id === id)!);
    const listing = {name, source: 'tmdb' as const, items: [
      ...members.map(movie => ({...movie, movie_id: movie.id, poster_url: ''})),
      {...members[0], title: '缺少的续集', movie_id: null, tmdb_id: '333', poster_url: 'https://image.tmdb.org/t/p/w342/movie.jpg', rating: 8.4, plot: '已缓存的续集剧情'},
    ]};
    vi.mocked(movieApi.series).mockResolvedValue(listing);
    vi.mocked(movieApi.allSeries).mockResolvedValue({groups: [listing,
      {name: '其他系列', source: 'tmdb', items: [{...listing.items[2], title: '另一部电影', tmdb_id: '444'}]}]});
    render(<MovieWall />);
    const intro = screen.getByTestId('movie-intro');
    const shortcuts = await within(intro).findByRole('region', {name: '系列各部'});
    fireEvent.click(within(shortcuts).getByRole('button', {name: second.title}));
    await within(intro).findByRole('heading', {name: second.title});
    fireEvent.click(screen.getByRole('button', {name: '海报墙'}));
    fireEvent.click(screen.getByRole('button', {name: '系列电影'}));
    const series = await screen.findByRole('dialog', {name: '系列、榜单与新片'});
    const missing = await within(series).findByRole('article', {name: '缺少的续集'});
    expect(within(series).getByRole('region', {name: '其他系列'})).toBeInTheDocument();
    expect(missing).toHaveTextContent('8.4');
    expect(within(missing).getAllByRole('link').map(link => link.textContent?.trim())).toEqual(['夸克盘搜', 'B站播放']);
    fireEvent.click(within(missing).getByRole('button'));
    const unownedDetail = await screen.findByRole('dialog', {name: '缺少的续集 · 电影简介'});
    expect(within(unownedDetail).getByText('已缓存的续集剧情')).toBeInTheDocument();
    expect(within(unownedDetail).queryByRole('link', {name: '打开夸克盘搜'})).not.toBeInTheDocument();
    expect(within(unownedDetail).queryByRole('link', {name: 'B站播放'})).not.toBeInTheDocument();
    fireEvent.click(within(unownedDetail).getByRole('button', {name: '关闭电影详情'}));
    await waitFor(() => expect(unownedDetail).not.toBeInTheDocument());
    fireEvent.change(within(series).getByRole('searchbox'), {target: {value: name}});
    expect(within(series).queryByRole('region', {name: '其他系列'})).not.toBeInTheDocument();
    const local = within(series).getByRole('article', {name: second.title});
    expect(within(local).getByRole('link', {name: '本地播放'})).toBeInTheDocument();
    series.scrollTop = 240;
    fireEvent.click(within(local).getByRole('button', {name: `${second.title}，查看简介`}));
    const detail = await screen.findByRole('dialog', {name: `${second.title} · 电影详情`});
    fireEvent.click(within(within(detail).getByRole('region', {name: '系列各部'})).getByRole('button', {name: first.title}));
    await screen.findByRole('dialog', {name: `${first.title} · 电影详情`});
    fireEvent.click(within(within(screen.getByRole('dialog', {name: `${first.title} · 电影详情`}))
      .getByRole('region', {name: '系列各部'}))
      .getByRole('button', {name: /缺少的续集/}));
    const externalDetail = await screen.findByRole('dialog', {name: '缺少的续集 · 电影简介'});
    expect(within(externalDetail).getByText('已缓存的续集剧情')).toBeInTheDocument();
    fireEvent.click(within(externalDetail).getByRole('button', {name: '关闭电影详情'}));
    fireEvent.click(within(detail).getByRole('button', {name: '关闭电影详情'}));
    await waitFor(() => expect(detail).not.toBeInTheDocument());
    expect(screen.getByRole('dialog', {name: '系列、榜单与新片'})).toBe(series);
    expect(within(series).getByRole('searchbox')).toHaveValue(name);
    expect(series.scrollTop).toBe(240);
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
    expect(preferredRating({...first, rating: 0, ratings: {themoviedb: 8.4}})).toEqual({source: 'tmdb', value: 8.4});
    expect(ratingForSource({...first, ratings: {tmdb: 8.6, themoviedb: 8.4}}, 'tmdb')).toBe(8.6);
    expect(new URL(localPlayUrl(first)).searchParams.get('path')).toBe(first.video_path);
  });
  it('播放在用户手势中使用独立窗口，失败时可见播放列表和完整路径',async()=>{
    render(<LocalPlayback movie={first}/>);
    const link=screen.getByRole('link',{name:'本地播放器播放'});
    expect(link).toHaveAttribute('target','_blank');
    expect(new URL(link.getAttribute('href')!).searchParams.get('path')).toBe(first.video_path);
    fireEvent.click(link);
    const help=await screen.findByRole('dialog',{name:'本地播放 · 第一部'});
    expect(within(help).getByRole('link',{name:'下载播放列表并打开'})).toHaveAttribute('href','/api/movie/movies/a/playlist.m3u8');
    expect(within(help).getByLabelText('视频路径')).toHaveValue(first.video_path);
  });
});
