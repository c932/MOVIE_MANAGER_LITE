import type {SubtitleTrack} from '../types/api';

export const subtitleLanguages: Record<string, string> = {
  'zh-Hans': '简中', 'zh-Hant': '繁中', zh: '中文', 'zh-en': '中英',
  en: '英语', ja: '日语', ko: '韩语', fr: '法语', de: '德语', es: '西语',
  it: '意语', pt: '葡语', ru: '俄语', und: '语言未知',
};

export function subtitleSummary(tracks: SubtitleTrack[] | null | undefined) {
  if (!tracks) return '字幕未检测';
  if (!tracks.length) return '无外挂字幕';
  return '字幕 ' + [...new Set(tracks.map(track => subtitleLanguages[track.language] || subtitleLanguages.und))].join(' / ');
}
