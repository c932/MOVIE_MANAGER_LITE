function movieQuery(title: string, originalTitle = '', year = '', play = false) {
  const values = [title.trim(), originalTitle.trim(), year.trim(), play ? '电影' : '']
    .filter(Boolean)
    .filter((value, index, all) => all.findIndex(item => item.toLocaleLowerCase() === value.toLocaleLowerCase()) === index);
  return values.join(' ');
}

function bridgeUrl(action: 'search' | 'play', keyword: string, fallback: string) {
  return `moviewall://bilibili/${action}?keyword=${encodeURIComponent(keyword)}&fallback=${encodeURIComponent(fallback)}`;
}

export function BilibiliActions({
  title, originalTitle = '', year = '', menu = false, onRequested,
}: {
  title: string;
  originalTitle?: string;
  year?: string;
  menu?: boolean;
  onRequested?: () => void;
}) {
  const searchQuery = movieQuery(title, originalTitle, year);
  const playQuery = movieQuery(title, originalTitle, year, true);
  const searchFallback = `https://search.bilibili.com/all?keyword=${encodeURIComponent(searchQuery)}`;
  const playFallback = `https://search.bilibili.com/video?keyword=${encodeURIComponent(playQuery)}&order=click`;
  const className = menu
    ? 'flex w-full items-center rounded px-3 py-2 text-left text-sm text-ink-200 hover:bg-ink-700'
    : 'btn';
  return <>
    <a role={menu ? 'menuitem' : undefined} className={className}
      href={bridgeUrl('search', searchQuery, searchFallback)}
      target="_blank" rel="noopener noreferrer" onClick={onRequested}
      title="本机已安装哔哩哔哩时优先打开客户端，否则回退到网页搜索">
      🔎 B站搜索
    </a>
    <a role={menu ? 'menuitem' : undefined} className={className}
      href={bridgeUrl('play', playQuery, playFallback)}
      target="_blank" rel="noopener noreferrer" onClick={onRequested}
      title="选择最匹配的B站视频；本机已安装哔哩哔哩时优先在客户端播放">
      ▶ B站播放
    </a>
  </>;
}
