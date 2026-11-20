import {beforeEach, expect, it, vi} from 'vitest';
import {fireEvent, render, screen, waitFor, within} from '@testing-library/react';
import {LibraryBrowseDialog} from '../components/movie/LibraryBrowseDialog';
import {movieApi} from '../api/client';
import type {RankingItem, RankingResponse, Job, MovieListItem} from '../types/api';

const owned: RankingItem = {rank: 1, title: '本库电影', year: '2025', original_title: '', rating: 8,
  poster_url: 'https://img3.doubanio.com/a.jpg', douban_id: '123', owned: true, in_library: true, movie_id: 'local-id'};
const missing: RankingItem = {...owned, rank: 2, title: '缺失电影', douban_id: '456', owned: false, in_library: false, movie_id: null};
const response: RankingResponse = {kind: 'chart', fetched_at: Date.now()/1000, items: [owned, missing], owned_count: 1, missing_count: 1};
const localMovie: MovieListItem = {
  id: 'local-id', title: '本库电影', original_title: '', year: '2025', premiered: '2025-01-01',
  plot: '完整剧情', tagline: '', runtime: '120', file_size: '', set_name: '',
  genres: ['动作'], countries: ['中国'], tags: [], rating: 8, rating_source: 'douban',
  ratings: {douban: 8, imdb: 7.8, tmdb: 7.6}, user_rating: 0, watched: false, favorite: false,
  directors: [], actors: [], resolution: '1080p', hdr_type: '', video_codec: '', audio_codec: '',
  imdb_id: '', tmdb_id: '', douban_url: '', video_path: '\\\\nas\\movie\\本库电影.mkv',
  nfo_path: '本库电影.nfo', poster_path: '本库电影.jpg', fanart_path: '', added_time: 0,
  has_poster: true, has_fanart: false, rank: null,
};
beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(movieApi, 'rankings').mockResolvedValue(response);
  vi.spyOn(movieApi, 'fetchRankings').mockResolvedValue({job_id: 'refresh'});
  vi.spyOn(movieApi, 'subject').mockResolvedValue({job_id: 'detail'});
  vi.spyOn(movieApi, 'get').mockResolvedValue({status: 'done', result: {plot: '该电影的真实剧情'}} as Job);
});

it('整张榜单卡打开本地详情浮窗且不关闭榜单', async () => {
  const select = vi.fn(), close = vi.fn();
  render(<LibraryBrowseDialog movies={[localMovie]} initial="chart" onSelect={select} onClose={close}/>);
  fireEvent.click(await screen.findByRole('button', {name: '本库电影，查看简介'}));
  expect(await screen.findByRole('dialog', {name: '本库电影 · 电影详情'})).toBeInTheDocument();
  expect(screen.getAllByRole('dialog').length).toBeGreaterThanOrEqual(2);
  expect(select).not.toHaveBeenCalled();
  expect(close).not.toHaveBeenCalled();
  expect(movieApi.subject).not.toHaveBeenCalled();
});

it('已入库电影即使榜单远程海报为空也加载本库海报', async () => {
  vi.mocked(movieApi.rankings).mockResolvedValue({...response,
    items: [{...owned, poster_url: ''}, missing]});
  const {container} = render(<LibraryBrowseDialog movies={[]} initial="chart" onSelect={vi.fn()} onClose={vi.fn()}/>);
  await screen.findByRole('button', {name: '本库电影，查看简介'});
  expect(container.querySelector('img')?.getAttribute('src')).toBe(movieApi.posterUrl('local-id', 240, 360));
});

it.each(['chart', 'nowplaying'] as const)('在 %s 卡片的夸克盘搜后直接提供 B 站播放', async initial => {
  const movie = {...missing, original_title: 'Other Title'};
  vi.mocked(movieApi.rankings).mockResolvedValue({...response, items: [movie]});
  vi.spyOn(movieApi, 'newMovies').mockResolvedValue({...response, items: [
    {title: missing.title, year: missing.year, poster_url: missing.poster_url, douban_id: missing.douban_id,
      genre: '', release_date: '', douban_url: '', rating: 0, movie_id: null, in_library: false},
  ]});
  const close = vi.fn();
  render(<LibraryBrowseDialog movies={[]} initial={initial} onSelect={vi.fn()} onClose={close}/>);
  const card = await screen.findByRole('article', {name: missing.title});
  const quark = within(card).getByRole('link', {name: '夸克盘搜'});
  const play = within(card).getByRole('link', {name: 'B站播放'}) as HTMLAnchorElement;
  expect(quark).toHaveAttribute('href', `https://www.zhongchuangwl.com/s/${encodeURIComponent(missing.title)}/`);
  expect(quark.compareDocumentPosition(play) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  const url = new URL(play.href);
  expect(`${url.protocol}//${url.host}${url.pathname}`).toBe('moviewall://bilibili/play');
  expect(url.searchParams.get('title')).toBe(missing.title);
  expect(url.searchParams.get('original_title')).toBe(initial === 'chart' ? movie.original_title : '');
  expect(url.searchParams.get('year')).toBe(missing.year);

  play.addEventListener('click', event => event.preventDefault());
  fireEvent.click(play);
  expect(screen.getAllByRole('dialog')).toHaveLength(1);
  expect(movieApi.subject).not.toHaveBeenCalled();
  expect(close).not.toHaveBeenCalled();
});

it('缺失电影显示简介、中创盘搜和 B 站入口', async () => {
  render(<LibraryBrowseDialog movies={[]} initial="chart" onSelect={vi.fn()} onClose={vi.fn()}/>);
  fireEvent.click(await screen.findByRole('button', {name: '缺失电影，查看简介'}));
  const dialog = await screen.findByRole('dialog', {name: '缺失电影 · 电影简介'});
  expect(await within(dialog).findByText('该电影的真实剧情')).toBeInTheDocument();
  expect(within(dialog).getByRole('link', {name: '打开夸克盘搜'})).toHaveAttribute('href', 'https://www.zhongchuangwl.com/s/'+encodeURIComponent('缺失电影')+'/');
  expect(within(dialog).getByRole('link', {name: '🔎 B站搜索'}).getAttribute('href')).toContain('https://search.bilibili.com/');
  expect(within(dialog).getByRole('link', {name: '▶ B站播放'}).getAttribute('href')).toContain('moviewall://bilibili/play?keyword=');
  expect(within(dialog).queryByRole('button', {name: /播放/})).not.toBeInTheDocument();
  expect(movieApi.subject).toHaveBeenCalledWith('456');
});

it('过期榜单自动刷新，刷新失败保留原条目并允许重试', async () => {
  vi.mocked(movieApi.rankings).mockResolvedValue({...response, fetched_at: 1});
  vi.mocked(movieApi.get).mockResolvedValue({status: 'error', error: '来源暂不可用'} as Job);
  render(<LibraryBrowseDialog movies={[]} initial="chart" onSelect={vi.fn()} onClose={vi.fn()}/>);
  expect(await screen.findByRole('alert')).toHaveTextContent('来源暂不可用');
  expect(screen.getByRole('button', {name: '本库电影，查看简介'})).toBeInTheDocument();
  expect(movieApi.fetchRankings).toHaveBeenCalledWith(['chart'], false);
  fireEvent.click(screen.getByRole('button', {name: '刷新榜单'}));
  await waitFor(() => expect(movieApi.fetchRankings).toHaveBeenCalledTimes(2));
});

it('年度分类切换不重新请求网络，年份切换读取对应榜单', async () => {
  const year = new Date().getFullYear()-1;
  vi.spyOn(movieApi,'annual').mockImplementation(async value => ({year: value, fetched_at: Date.now()/1000,
    categories: [{id:'a',title:'评分最高华语电影',items:[owned]}, {id:'b',title:'冷门佳片',items:[missing]}]}));
  render(<LibraryBrowseDialog movies={[]} initial="annual" onSelect={vi.fn()} onClose={vi.fn()}/>);
  await screen.findByRole('button', {name:'本库电影，查看简介'});
  fireEvent.change(screen.getByLabelText('年度电影分类'), {target:{value:'b'}});
  expect(screen.getByRole('button', {name:'缺失电影，查看简介'})).toBeInTheDocument();
  expect(movieApi.annual).toHaveBeenCalledTimes(1);
  fireEvent.change(screen.getByLabelText('榜单年度'),{target:{value:String(year-1)}});
  await waitFor(()=>expect(movieApi.annual).toHaveBeenCalledWith(year-1));
});
