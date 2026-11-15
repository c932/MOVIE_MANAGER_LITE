import {request} from './client';
import type {MovieListItem} from '../types/api';

export interface ScrapeRow {
  id: string; movie_id: string; movie: MovieListItem; is_new: boolean; status: string;
  poster_exists: boolean | null; subtitle_count: number | null; error_kind: string; error: string;
}
export interface Candidate {
  token: string; source: string; id: string; title: string; original_title: string; year: string;
  overview: string; poster_url: string;
}
export interface Draft {
  session: string; target_id: string; fields: Partial<MovieListItem> & {uniqueids?: Record<string,string>};
  votes: Record<string,number>; artwork: {url: string; preview_url: string; width: number; height: number; source: string; language: string}[];
  poster_index?: number|null;
  warnings: string[]; confirmed: boolean; replace_identity: boolean; can_rebuild: boolean;
  plot_source: string; source_plots: Record<string,string>; sources: string[]; write_blocked: string; target_path: string;
}
export interface EditorSnapshot {session: string; movie: MovieListItem; uniqueids: Record<string,string>; votes: Record<string,number>}
export interface ScrapeSettings {
  tmdb_api_key?: string; tmdb_token?: string; omdb_api_key?: string; has_tmdb_api_key: boolean;
  has_tmdb_token: boolean; has_omdb_api_key: boolean; language: string; proxy: string;
  timeout: number; douban_delay: number; douban_available: boolean;
}
export interface SaveOptions {
  selected_fields: string[]; overwrite: boolean; metadata_only: boolean; replace_identity_ack: boolean;
}
export const writeFields: [string,string][] = [['title','标题'],['original_title','原名'],['year','年份'],['premiered','上映日期'],
  ['plot','简介'],['tagline','宣传语'],['runtime','片长'],['genres','类型'],['countries','国家地区'],['directors','导演'],
  ['actors','演员'],['set_name','系列'],['uniqueids','来源 ID / 链接'],['ratings','评分 / 人数'],['poster','海报']];

const base = '/api/movie/scrape';
const post = (url: string, body: unknown = {}) => request<{job_id:string}>(base + url, {method:'POST', body: JSON.stringify(body)});
export const scrapeApi = {
  rows: () => request<{rows:ScrapeRow[]}>(base+'/workspace'),
  scan: () => post('/workspace/scan'),
  settings: () => request<ScrapeSettings>(base+'/settings'),
  saveSettings: (body: Partial<ScrapeSettings>) => request<ScrapeSettings>(base+'/settings',{method:'PUT',body:JSON.stringify(body)}),
  search: (source: string, query: string, year: string, page: number) => post('/search',{source,query,year,page}),
  preview: (target_id: string, candidate: string, previous?: string) => post('/preview',{target_id,candidate,previous}),
  confirm: (session: string, body: {plot_source:string;title:string;plot:string;poster_index:number|null;rebuild_nfo:boolean}) => post('/sessions/'+session+'/confirm',body),
  save: (session: string, body: SaveOptions) => post('/sessions/'+session+'/save',body),
  edit: (target: string) => post('/edit/'+target),
  saveEditor: (session: string, changes: object, votes: object, poster_base64?: string) => post('/edit/sessions/'+session+'/save',{changes,votes,poster_base64}),
};
