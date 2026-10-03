// 游戏封面卡片 — 暗色放映厅风格，arcade 身份色
import { memo, useState } from 'react';
import { gameApi } from '../../api/client';
import { TIER_COLORS } from '../../stores/gameStore';
import type { GameListItem } from '../../types/api';

interface Props {
  game: GameListItem;
  scale: number;
  selected: boolean;
  onSelect: (game: GameListItem) => void;
  onContextMenu: (game: GameListItem, x: number, y: number) => void;
}

const BASE_W = 184;
const BASE_H = 276; // 竖版封面比例

export const GameCard = memo(function GameCard({
  game,
  scale,
  selected,
  onSelect,
  onContextMenu,
}: Props) {
  const [imgFailed, setImgFailed] = useState(false);
  const w = Math.round(BASE_W * (scale / 100));
  const h = Math.round(BASE_H * (scale / 100));

  const showImage = game.has_cover && !imgFailed;

  return (
    <div
      className="poster-card relative cursor-pointer select-none"
      style={{ width: w, height: h }}
      onClick={() => onSelect(game)}
      onContextMenu={(e) => {
        e.preventDefault();
        onContextMenu(game, e.clientX, e.clientY);
      }}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && onSelect(game)}
    >
      <div
        className={`relative h-full w-full overflow-hidden rounded-lg bg-ink-800 ${
          selected ? 'ring-2 ring-arcade-400' : 'ring-1 ring-ink-700'
        }`}
      >
        {showImage ? (
          <img
            src={gameApi.coverUrl(game.key, w, h, 'grid')}
            alt={game.title_cn}
            loading="lazy"
            className="h-full w-full object-contain"
            onError={() => setImgFailed(true)}
            draggable={false}
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center p-2 text-center text-xs text-ink-400">
            {game.title_cn}
          </div>
        )}

        {/* 档位徽章 */}
        <span
          className={`absolute left-1.5 top-1.5 rounded px-1.5 py-0.5 text-2xs font-semibold ${TIER_COLORS[game.tier]}`}
        >
          {game.tier}
        </span>

        {/* 评分 */}
        {game.rating > 0 && (
          <span className="rating-badge absolute right-1.5 top-1.5 rounded bg-black/70 px-1.5 py-0.5 text-xs text-gold backdrop-blur-sm">
            {game.rating.toFixed(1)}
          </span>
        )}

        {/* 底部标题条 */}
        <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/85 via-black/50 to-transparent px-2 pb-1.5 pt-6">
          <div className="truncate text-xs font-medium text-ink-50">
            {game.title_cn}
          </div>
          {game.title_en && (
            <div className="truncate text-2xs text-ink-300">{game.title_en}</div>
          )}
        </div>

        {/* 已安装角标 */}
        {game.installed && (
          <span className="absolute bottom-1.5 right-1.5 rounded bg-arcade-600 px-1 text-2xs font-medium text-ink-950">
            已安装
          </span>
        )}
      </div>
    </div>
  );
});