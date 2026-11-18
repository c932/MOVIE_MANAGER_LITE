import {beforeEach, expect, it, vi} from 'vitest';
import {fireEvent, render, screen, waitFor, within} from '@testing-library/react';
import {LibraryBrowseDialog} from '../components/movie/LibraryBrowseDialog';
import {movieApi} from '../api/client';
import type {RankingItem, RankingResponse, Job} from '../types/api';

const owned: RankingItem = {rank: 1, title: '本库电影', year: '2025', original_title: '', rating: 8,
  poster_url: 'https://img3.doubanio.com/a.jpg', douban_id: '123', owned: true, in_library: true, movie_id: 'local-id'};
const missing: RankingItem = {...owned, rank: 2, title: '缺失电影', douban_id: '456', owned: false, in_library: false, movie_id: null};
const response: RankingResponse = {kind: 'chart', fetched_at: Date.now()/1000, items: [owned, missing], owned_count: 1, missing_count: 1};
beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(movieApi, 'rankings').mockResolvedValue(response);
  vi.spyOn(movieApi, 'fetchRankings').mockResolvedValue({job_id: 'refresh'});
  vi.spyOn(movieApi, 'subject').mockResolvedValue({job_id: 'detail'});
  vi.spyOn(movieApi, 'get').mockResolvedValue({status: 'done', result: {plot: '该电影的真实剧情'}} as Job);
});

it('整张榜单卡进入已有电影本地详情', async () => {
  const select = vi.fn(), close = vi.fn();
  render(<LibraryBrowseDialog movies={[]} initial="chart" onSelect={select} onClose={close}/>);
  fireEvent.click(await screen.findByRole('button', {name: '本库电影，查看本库电影'}));
  expect(select).toHaveBeenCalledWith('local-id'); expect(close).toHaveBeenCalledOnce();
  expect(movieApi.subject).not.toHaveBeenCalled();
});

it('已入库电影即使榜单远程海报为空也加载本库海报', async () => {
  vi.mocked(movieApi.rankings).mockResolvedValue({...response,
    items: [{...owned, poster_url: ''}, missing]});
  const {container} = render(<LibraryBrowseDialog movies={[]} initial="chart" onSelect={vi.fn()} onClose={vi.fn()}/>);
  await screen.findByRole('button', {name: '本库电影，查看本库电影'});
  expect(container.querySelector('img')?.getAttribute('src')).toBe(movieApi.posterUrl('local-id', 240, 360));
});

it('缺失电影显示简介和中创盘搜，没有播放操作', async () => {
  render(<LibraryBrowseDialog movies={[]} initial="chart" onSelect={vi.fn()} onClose={vi.fn()}/>);
  fireEvent.click(await screen.findByRole('button', {name: '缺失电影，查看简介'}));
  const dialog = await screen.findByRole('dialog', {name: '缺失电影 · 电影简介'});
  expect(await within(dialog).findByText('该电影的真实剧情')).toBeInTheDocument();
  expect(within(dialog).getByRole('link', {name: '打开夸克盘搜'})).toHaveAttribute('href', 'https://www.zhongchuangwl.com/s/'+encodeURIComponent('缺失电影')+'/');
  expect(within(dialog).queryByRole('button', {name: /播放/})).not.toBeInTheDocument();
  expect(movieApi.subject).toHaveBeenCalledWith('456');
});

it('过期榜单自动刷新，刷新失败保留原条目并允许重试', async () => {
  vi.mocked(movieApi.rankings).mockResolvedValue({...response, fetched_at: 1});
  vi.mocked(movieApi.get).mockResolvedValue({status: 'error', error: '来源暂不可用'} as Job);
  render(<LibraryBrowseDialog movies={[]} initial="chart" onSelect={vi.fn()} onClose={vi.fn()}/>);
  expect(await screen.findByRole('alert')).toHaveTextContent('来源暂不可用');
  expect(screen.getByRole('button', {name: '本库电影，查看本库电影'})).toBeInTheDocument();
  expect(movieApi.fetchRankings).toHaveBeenCalledWith(['chart'], false);
  fireEvent.click(screen.getByRole('button', {name: '刷新榜单'}));
  await waitFor(() => expect(movieApi.fetchRankings).toHaveBeenCalledTimes(2));
});

it('年度分类切换不重新请求网络，年份切换读取对应榜单', async () => {
  const year = new Date().getFullYear()-1;
  vi.spyOn(movieApi,'annual').mockImplementation(async value => ({year: value, fetched_at: Date.now()/1000,
    categories: [{id:'a',title:'评分最高华语电影',items:[owned]}, {id:'b',title:'冷门佳片',items:[missing]}]}));
  render(<LibraryBrowseDialog movies={[]} initial="annual" onSelect={vi.fn()} onClose={vi.fn()}/>);
  await screen.findByRole('button', {name:'本库电影，查看本库电影'});
  fireEvent.change(screen.getByLabelText('年度电影分类'), {target:{value:'b'}});
  expect(screen.getByRole('button', {name:'缺失电影，查看简介'})).toBeInTheDocument();
  expect(movieApi.annual).toHaveBeenCalledTimes(1);
  fireEvent.change(screen.getByLabelText('榜单年度'),{target:{value:String(year-1)}});
  await waitFor(()=>expect(movieApi.annual).toHaveBeenCalledWith(year-1));
});
