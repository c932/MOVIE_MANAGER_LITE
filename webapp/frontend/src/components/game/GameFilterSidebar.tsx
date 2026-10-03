// 游戏墙筛选侧栏
import { useGameStore, TIER_LIST, TIER_COLORS } from '../../stores/gameStore';

export function GameFilterSidebar() {
  const s = useGameStore();
  const opts = s.filterOptions();

  return (
    <div className="flex h-full flex-col overflow-y-auto p-3">
      {/* 搜索 */}
      <div className="mb-4">
        <input
          className="input w-full"
          placeholder="搜索游戏名…"
          value={s.search}
          onChange={(e) => s.setSearch(e.target.value)}
        />
      </div>

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

      {/* 档位 */}
      <Section title="特性">
        <div className="flex flex-wrap gap-1.5">
          {TIER_LIST.map((tier) => (
            <button
              key={tier}
              className={`rounded px-2 py-1 text-xs font-medium ${TIER_COLORS[tier]} ${
                s.selectedTiers.has(tier) ? 'ring-1 ring-white/40' : 'opacity-60'
              }`}
              onClick={() => s.toggleTier(tier)}
            >
              {tier}
            </button>
          ))}
        </div>
        <div className="mt-2 flex gap-1.5">
          <button
            className={`tag ${s.installedOnly ? 'tag-active-arcade' : ''}`}
            onClick={() => s.setInstalledOnly(!s.installedOnly)}
          >
            已安装
          </button>
        </div>
      </Section>

      {/* Steam 评分 */}
      <Section title="Steam 评分">
        {[
          { v: 0, label: '全部' },
          { v: 90, label: '≥90%' },
          { v: 75, label: '≥75%' },
          { v: 50, label: '≥50%' },
          { v: -1, label: '无评分' },
        ].map((r) => (
          <button
            key={r.v}
            className={`tag mr-1.5 ${s.ratingBand === r.v ? 'tag-active-arcade' : ''}`}
            onClick={() => s.setRatingBand(r.v)}
          >
            {r.label}
          </button>
        ))}
      </Section>

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

      {/* 制作公司 */}
      {opts.developers.length > 0 && (
        <Section title="制作公司">
          <TagGroup
            items={opts.developers}
            selected={s.selectedDevelopers}
            onToggle={s.toggleDeveloper}
          />
        </Section>
      )}

      {/* 重置 */}
      <div className="mt-auto pt-3">
        <button className="btn btn-arcade w-full" onClick={s.resetFilters}>
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
          className={`tag ${selected.has(item) ? 'tag-active-arcade' : ''}`}
          onClick={() => onToggle(item)}
        >
          {item}
        </button>
      ))}
    </div>
  );
}
