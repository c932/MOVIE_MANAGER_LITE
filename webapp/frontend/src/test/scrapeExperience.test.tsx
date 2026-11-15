import {beforeEach,describe,it,expect,vi} from 'vitest';
import {render,screen,fireEvent,waitFor} from '@testing-library/react';
import {SearchScrapeDialog} from '../components/movie/SearchScrapeDialog';
import {MetadataEditor} from '../components/movie/MetadataEditor';
import {StrictMode} from 'react';
import {scrapeApi} from '../api/scrape';
import {movieApi} from '../api/client';
import type {ScrapeRow,Draft} from '../api/scrape';
import type {Job,MovieListItem} from '../types/api';

vi.mock('../api/scrape',async original=>({...await original<typeof import('../api/scrape')>(),scrapeApi:{search:vi.fn(),preview:vi.fn(),confirm:vi.fn(),save:vi.fn(),edit:vi.fn(),saveEditor:vi.fn()}}));
vi.mock('../api/client',()=>({movieApi:{get:vi.fn(),proxyImageUrl:(url:string)=>url,posterUrl:()=>'/poster.jpg'}}));
const row=(id:string,title:string)=>({id,movie_id:id,movie:{id,title,year:'2016',original_title:'',video_path:'\\\\nas\\movie\\'+id+'.mkv',ratings:{douban:7,imdb:8,tmdb:9}} as unknown as MovieListItem,is_new:false,status:'待补信息',poster_exists:true,subtitle_count:null,error_kind:'',error:''} as ScrapeRow);
const rows=[row('a','电影甲'),row('b','电影乙')];
const draft={votes:{},session:'draft1',target_id:'a',fields:{title:'正确的电影',year:'2016',plot:'豆瓣剧情',ratings:{tmdb:9,imdb:8,douban:7}},artwork:[],warnings:[],confirmed:false,plot_source:'douban',source_plots:{douban:'豆瓣剧情',tmdb:'TMDB 剧情'},sources:['douban','tmdb'],write_blocked:'',target_path:'a.nfo',replace_identity:false,can_rebuild:false} as Draft;
beforeEach(()=>{
  vi.clearAllMocks();
  vi.mocked(scrapeApi.search).mockResolvedValue({job_id:'search'});
  vi.mocked(scrapeApi.preview).mockResolvedValue({job_id:'preview'});
  vi.mocked(scrapeApi.confirm).mockResolvedValue({job_id:'confirm'});
  vi.mocked(scrapeApi.save).mockResolvedValue({job_id:'save'});
  vi.mocked(movieApi.get).mockImplementation(async id=>({id,status:'done',result:id==='search'?[{token:'candidate',title:'正确的电影',year:'2016',source:'douban',id:'12'}]:id==='preview'?draft:id==='confirm'?{...draft,confirmed:true}:rows[0].movie} as Job));
});
describe('网页搜索与刮削',()=>{
  it('上一部、下一部切换目标并重置搜索，首尾禁用',()=>{
    render(<SearchScrapeDialog rows={rows} onClose={()=>{}} onSaved={()=>{}}/>);
    expect(screen.getByRole('button',{name:'上一部'})).toBeDisabled();
    fireEvent.click(screen.getByRole('button',{name:'下一部 / 跳过'}));
    expect(screen.getByRole('dialog').getAttribute('aria-label')).toContain('电影乙');
    expect(screen.getByLabelText('片名')).toHaveValue('电影乙');
    expect(screen.getByRole('button',{name:'下一部 / 跳过'})).toBeDisabled();
    fireEvent.click(screen.getByRole('button',{name:'上一部'}));
    expect(screen.getByLabelText('片名')).toHaveValue('电影甲');
  });
  it('预览保留三源评分，豆瓣默认简介，确认后才能保存',async()=>{
    const saved=vi.fn();
    render(<SearchScrapeDialog rows={rows} onClose={()=>{}} onSaved={saved}/>);
    fireEvent.click(screen.getByRole('button',{name:'搜索'}));
    fireEvent.click(await screen.findByRole('button',{name:'正确的电影'}));
    await screen.findByText('TMDB：9.0');
    expect(screen.getByText('IMDb：8.0')).toBeInTheDocument();
    expect(screen.getByText('豆瓣：7.0')).toBeInTheDocument();
    expect(screen.getByLabelText('简介来源')).toHaveValue('douban');
    expect(screen.getByRole('button',{name:'保存当前电影'})).toBeDisabled();
    fireEvent.click(screen.getByRole('button',{name:'确认匹配 / 补充来源'}));
    await waitFor(()=>expect(screen.getByRole('button',{name:'保存当前电影'})).toBeEnabled());
    fireEvent.click(screen.getByRole('button',{name:'保存当前电影'}));
    await waitFor(()=>expect(saved).toHaveBeenCalledOnce());
    expect(scrapeApi.save).toHaveBeenCalledWith('draft1',expect.objectContaining({selected_fields:expect.arrayContaining(['ratings','uniqueids','set_name'])}));
  });
  it('严格模式可打开编辑，国家与导演可输入多词、多个值，只提交改动',async()=>{
    vi.mocked(scrapeApi.edit).mockResolvedValue({job_id:'edit'});
    vi.mocked(scrapeApi.saveEditor).mockResolvedValue({job_id:'saveEdit'});
    const movie={...rows[0].movie,countries:['美国'],genres:['动作'],directors:['甲导演'],actors:[],ratings:{douban:7,imdb:8,tmdb:9,rottentomatoes:91}};
    vi.mocked(movieApi.get).mockImplementation(async id=>({id,status:'done',result:id==='edit'?{session:'editor',movie,uniqueids:{},votes:{}}:movie} as Job));
    render(<StrictMode><MetadataEditor row={rows[0]} onClose={()=>{}} onSaved={()=>{}}/></StrictMode>);
    const country=await screen.findByLabelText('国家地区（用 / 分隔）');
    fireEvent.change(country,{target:{value:'United Kingdom / United States'}});
    expect(country).toHaveValue('United Kingdom / United States');
    fireEvent.click(screen.getByRole('button',{name:'演职人员'}));
    fireEvent.change(screen.getByLabelText('导演（用 / 分隔）'),{target:{value:'John Smith / 王二'}});
    fireEvent.click(screen.getByRole('button',{name:'保存修改'}));
    await waitFor(()=>expect(scrapeApi.saveEditor).toHaveBeenCalledWith('editor',{countries:['United Kingdom','United States'],directors:['John Smith','王二']},{},undefined));
  });
});
