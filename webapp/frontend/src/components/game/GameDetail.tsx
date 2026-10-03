// 游戏详情面板
import { useState } from 'react';
import { gameApi } from '../../api/client';
import { TIER_COLORS, TIER_LIST } from '../../stores/gameStore';
import type { GameListItem, Tier } from '../../types/api';

interface Props {
  game: GameListItem | null;
  onUpdated: (game: GameListItem) => void;
  onEdit: (game: GameListItem) => void;
}

export function GameDetail({ game, onUpdated, onEdit }: Props) {
  const [coverVersion, setCoverVersion] = useState(0);
  if (!game) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-ink-400">
        选择一款游戏查看详情
      </div>
    );
  }

  const coverW = 280;
  const coverH = 420;
  const coverUrl = game.has_cover
    ? `${gameApi.coverUrl(game.key, coverW, coverH, 'grid')}?v=${coverVersion}`
    : null;

  const setTier = async (tier: Tier | null) => {
    try {
      const updated = await gameApi.setTier(game.key, tier);
      onUpdated(updated);
    } catch (e) {
      alert((e as Error).message);
    }
  };

  const refreshCover = async () => {
    try {
      await gameApi.refreshCover(game.key);
      setCoverVersion((v) => v + 1);
    } catch (e) {
      alert((e as Error).message);
    }
  };

  const ratingSources = [
    game.metacritic > 0 && { label: 'Metacritic', value: game.metacritic },
    game.ign_score > 0 && { label: 'IGN', value: game.ign_score },
    game.gamersky_score > 0 && { label: 'Gamersky', value: game.gamersky_score },
    game.steam_positive_pct > 0 && { label: 'Steam 好评', value: `${game.steam_positive_pct}%` },
  ].filter(Boolean) as { label: string; value: string | number }[];

  return (
    <div className="flex h-full gap-5 overflow-y-auto p-4">
      {/* 左：封面 */}
      <div className="shrink-0">
        {coverUrl ? (
          <img
            src={coverUrl}
            alt={game.title_cn}
            className="rounded-lg shadow-2xl ring-1 ring-ink-700"
            style={{ width: coverW, height: coverH }}
            draggable={false}
          />
        ) : (
          <div
            className="flex items-center justify-center rounded-lg bg-ink-800 text-sm text-ink-400 ring-1 ring-ink-700"
            style={{ width: coverW, height: coverH }}
          >
            无封面
          </div>
        )}
      </div>

      {/* 右：信息 */}
      <div className="flex min-w-0 flex-1 flex-col gap-3">
        <div>
          <h2 className="text-xl font-semibold text-ink-50">{game.title_cn}</h2>
          {game.title_en && <p className="text-sm text-ink-300">{game.title_en}</p>}
          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-ink-300">
            {game.developer && <span>{game.developer}</span>}
            {game.release_date && <span>{game.release_date}</span>}
            {game.version && <span className="font-mono">v{game.version}</span>}
            {game.size_text && <span className="font-mono">{game.size_text}</span>}
          </div>
        </div>

        {/* 档位 */}
        <div className="flex flex-wrap items-center gap-2">
          <span className={`rounded px-2 py-1 text-xs font-semibold ${TIER_COLORS[game.tier]}`}>
            {game.tier}
          </span>
          <span className="text-2xs text-ink-400">来源：{game.tier_source}</span>
        </div>

        {/* 评分 */}
        {ratingSources.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {ratingSources.map((r) => (
              <div
                key={r.label}
                className="flex items-center gap-1.5 rounded-lg bg-ink-800 px-3 py-1.5"
              >
                <span className="text-2xs text-ink-300">{r.label}</span>
                <span className="font-mono text-sm font-semibold text-gold">
                  {r.value}
                </span>
              </div>
            ))}
          </div>
        )}

        {/* 类型 / 平台 */}
        <div className="flex flex-wrap gap-1.5">
          {game.genres.map((g) => (
            <span key={g} className="tag">
              {g}
            </span>
          ))}
          {game.platforms.map((p) => (
            <span key={p} className="tag">
              {p}
            </span>
          ))}
        </div>

        {/* 简介 */}
        {game.description && (
          <p className="max-h-32 overflow-y-auto text-sm leading-relaxed text-ink-200">
            {game.description}
          </p>
        )}

        {/* 按钮栏 */}
        <div className="mt-auto flex flex-wrap gap-2 border-t divider pt-3">
          <span className="self-center text-2xs text-ink-400">标记档位：</span>
          {TIER_LIST.map((tier) => (
            <button
              key={tier}
              className={`rounded px-2 py-1 text-xs font-medium transition-opacity ${TIER_COLORS[tier]} ${
                game.tier === tier ? 'opacity-100 ring-1 ring-white/40' : 'opacity-60 hover:opacity-100'
              }`}
              onClick={() => setTier(tier)}
            >
              {tier}
            </button>
          ))}
          <button
            className="btn text-ink-300"
            onClick={() => setTier(null)}
            title="恢复自动判断"
          >
            恢复自动
          </button>

          <div className="ml-auto flex gap-2">
            {game.quark_link && (
              <a
                className="btn btn-arcade"
                href={game.quark_link}
                target="_blank"
                rel="noreferrer"
              >
                🌐 下载链接
              </a>
            )}
            <button className="btn" onClick={refreshCover}>
              🖼 刷新封面
            </button>
            <button className="btn" onClick={() => onEdit(game)}>
              📝 编辑
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
