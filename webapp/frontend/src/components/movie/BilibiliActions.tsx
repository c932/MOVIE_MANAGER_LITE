function movieQuery(title: string, originalTitle = '', year = '', play = false) {
  const values = [title.trim(), originalTitle.trim(), year.trim(), play ? '电影' : '']
    .filter(Boolean)
    .filter((value, index, all) => all.findIndex(item => item.toLocaleLowerCase() === value.toLocaleLowerCase()) === index);
  return values.join(' ');
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
  const searchUrl = `https://search.bilibili.com/all?keyword=${encodeURIComponent(searchQuery)}`;
  const playParams = new URLSearchParams({keyword: playQuery, title, original_title: originalTitle, year});
  const className = menu
    ? 'flex w-full items-center rounded px-3 py-2 text-left text-sm text-ink-200 hover:bg-ink-700'
    : 'btn';
  return <>
    <a role={menu ? 'menuitem' : undefined} className={className}
      href={searchUrl}
      target="_blank" rel="noopener noreferrer" onClick={onRequested}
      title="在 B 站网页搜索片名">
      🔎 B站搜索
    </a>
    <a role={menu ? 'menuitem' : undefined} className={className}
      href={`moviewall://bilibili/play?${playParams}`} onClick={onRequested}
      title="需要 Windows 电影墙 3.6.1 或更新版。找到匹配视频时优先使用 B 站客户端。">
      ▶ B站播放
    </a>
  </>;
}
