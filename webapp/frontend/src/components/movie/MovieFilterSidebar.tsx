// 电影墙筛选侧栏
import { useMovieStore } from '../../stores/movieStore';

export function MovieFilterSidebar() {
  const s = useMovieStore();
  const opts = s.filterOptions();

  return (
    <div className="flex h-full flex-col overflow-y-auto p-3">
      {/* 搜索 */}
      <div className="mb-4">
        <input
          className="input w-full"
          placeholder="搜索片名/导演/演员…"
          value={s.search}
          onChange={(e) => s.setSearch(e.target.value)}
        />
        <button
          className={`mt-1.5 w-full text-left text-xs ${
            s.searchDuplicate ? 'text-cinema-400' : 'text-ink-300'
          }`}
          onClick={() => s.setSearchDuplicate(!s.searchDuplicate)}
        >
          {s.searchDuplicate ? '✓ ' : ''}同名重复筛选
        </button>
      </div>

      {/* 观看/收藏 */}
      <Section title="状态">
        <div className="flex gap-1.5">
          {[
            { v: 0, label: '全部' },
            { v: 1, label: '已看' },
            { v: 2, label: '未看' },
          ].map((w) => (
            <button
              key={w.v}
              className={`tag ${s.watchFilter === w.v ? 'tag-active' : ''}`}
              onClick={() => s.setWatchFilter(w.v as 0 | 1 | 2)}
            >
              {w.label}
            </button>
          ))}
        </div>
        <div className="mt-1.5 flex gap-1.5">
          {[
            { v: 0, label: '全部' },
            { v: 1, label: '已收藏' },
          ].map((f) => (
            <button
              key={f.v}
              className={`tag ${s.favoriteFilter === f.v ? 'tag-active' : ''}`}
              onClick={() => s.setFavoriteFilter(f.v as 0 | 1)}
            >
              {f.label}
            </button>
          ))}
        </div>
      </Section>

      {/* 最低评分 */}
      <Section title={`评分 ≥ ${s.minRating.toFixed(1)}`}>
        <input
          type="range"
          min={0}
          max={10}
          step={0.5}
          value={s.minRating}
          onChange={(e) => s.setMinRating(parseFloat(e.target.value))}
          className="w-full accent-cinema-500"
        />
      </Section>

      {/* 类型 */}
      {opts.genres.length > 0 && (
        <Section title="类型">
          <TagGroup
            items={opts.genres}
            selected={s.selectedGenres}
            onToggle={s.toggleGenre}
          />
        </Section>
      )}

      {/* 国家 */}
      {opts.countries.length > 0 && (
        <Section title="国家/地区">
          <TagGroup
            items={opts.countries}
            selected={s.selectedCountries}
            onToggle={s.toggleCountry}
          />
        </Section>
      )}

      {/* 年份 */}
      {opts.years.length > 0 && (
        <Section title="年份">
          <TagGroup
            items={opts.years}
            selected={s.selectedYears}
            onToggle={s.toggleYear}
          />
        </Section>
      )}

      {/* 重置 */}
      <div className="mt-auto pt-3">
        <button className="btn w-full" onClick={s.resetFilters}>
          🔄 重置筛选
        </button>
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mb-4">
      <h3 className="mb-2 text-xs font-medium text-ink-300">{title}</h3>
      {children}
    </div>
  );
}

function TagGroup({
  items,
  selected,
  onToggle,
}: {
  items: string[];
  selected: Set<string>;
  onToggle: (item: string) => void;
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((item) => (
        <button
          key={item}
          className={`tag ${selected.has(item) ? 'tag-active' : ''}`}
          onClick={() => onToggle(item)}
        >
          {item}
        </button>
      ))}
    </div>
  );
}