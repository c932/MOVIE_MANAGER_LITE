export function BilibiliActions({
  title, originalTitle = '', year = '', menu = false, onRequested,
}: {
  title: string;
  originalTitle?: string;
  year?: string;
  menu?: boolean;
  onRequested?: () => void;
}) {
  const keyword = title.trim() || originalTitle.trim();
  const searchUrl = `https://search.bilibili.com/pgc?${new URLSearchParams({keyword})}`;
  const playParams = new URLSearchParams({keyword, title, original_title: originalTitle, year, fallback: searchUrl});
  const className = menu
    ? 'flex w-full items-center rounded px-3 py-2 text-left text-sm text-ink-200 hover:bg-ink-700'
    : 'btn';
  return <>
    <a role={menu ? 'menuitem' : undefined} className={className}
      href={searchUrl}
      target="_blank" rel="noopener noreferrer" onClick={onRequested}
      title="在 B 站影视分类搜索片名">
      🔎 B站搜索
    </a>
    <a role={menu ? 'menuitem' : undefined} className={className}
      href={`moviewall://bilibili/play?${playParams}`} onClick={onRequested}
      title="需要 Windows 电影墙 3.6.2 或更新版。有官方电影时打开 B 站影视结果。">
      ▶ B站播放
    </a>
  </>;
}
