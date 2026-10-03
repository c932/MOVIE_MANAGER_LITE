// 游戏墙主页面
import { useCallback, useEffect, useMemo, useState } from 'react';
import { gameApi } from '../api/client';
import { useJobPoll } from '../hooks/useJobPoll';
import { JobProgress } from '../components/JobProgress';
import { GameCard } from '../components/game/GameCard';
import { GameDetail } from '../components/game/GameDetail';
import { GameFilterSidebar } from '../components/game/GameFilterSidebar';
import { GameSettingsDialog } from '../components/game/GameSettingsDialog';
import { useGameStore } from '../stores/gameStore';
import type { GameListItem } from '../types/api';

export default function GameWall() {
  const store = useGameStore();
  const [enrichJobId, setEnrichJobId] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [contextMenu, setContextMenu] = useState<{
    game: GameListItem;
    x: number;
    y: number;
  } | null>(null);

  useEffect(() => {
    store.load();
  }, []);

  const { job: enrichJob } = useJobPoll(
    gameApi,
    enrichJobId,
    800,
    useCallback(() => {
      store.load();
      setEnrichJobId(null);
    }, [store]),
  );

  const games = store.filtered();
  const selectedGame = useMemo(
    () => store.games.find((g) => g.key === store.selectedKey) || null,
    [store.games, store.selectedKey],
  );

  const handleSelect = (game: GameListItem) => {
    store.selectGame(game.key);
    setContextMenu(null);
  };

  const handleContextMenu = (game: GameListItem, x: number, y: number) => {
    setContextMenu({ game, x, y });
  };

  const handleUpdate = (game: GameListItem) => {
    store.updateGame(game);
  };

  const handleEdit = (game: GameListItem) => {
    // TODO: edit dialog
    alert(`编辑: ${game.title_cn}`);
  };

  const handleEnrichAll = async () => {
    const { job_id } = await gameApi.enrich('all', [], { steam: true, ratings: true });
    setEnrichJobId(job_id);
  };

  const job = enrichJob;

  return (
    <div className="flex h-screen overflow-hidden">
      {/* 左侧筛选 */}
      <aside className="flex w-64 shrink-0 flex-col border-r divider bg-ink-900">
        <div className="flex items-center justify-between border-b divider px-3 py-2">
          <span className="text-sm font-semibold text-ink-50">游戏墙</span>
          <span className="text-2xs text-ink-400">{games.length} 款</span>
        </div>
        <div className="flex-1 overflow-y-auto">
          <GameFilterSidebar />
        </div>
      </aside>

      {/* 右侧主区域 */}
      <main className="flex min-w-0 flex-1 flex-col">
        {/* 工具栏 */}
        <div className="flex shrink-0 items-center gap-2 border-b divider bg-ink-850 px-3 py-2">
          {/* 排序 */}
          {(
            [
              ['update', '更新'],
              ['rating', '评分'],
              ['release', '发售'],
              ['name', '名称'],
            ] as [string, string][]
          ).map(([mode, label]) => (
            <button
              key={mode}
              className={`btn ${store.sortMode === mode ? 'btn-active' : ''}`}
              onClick={() => store.setSortMode(mode as typeof store.sortMode)}
            >
              {label}
            </button>
          ))}

          <div className="h-5 w-px bg-ink-700" />

          {/* 缩放 */}
          <span className="text-2xs text-ink-400">缩放</span>
          <input
            type="range"
            min={50}
            max={200}
            value={store.posterScale}
            onChange={(e) => store.setPosterScale(parseInt(e.target.value))}
            className="w-20 accent-arcade-500"
          />

          <div className="h-5 w-px bg-ink-700" />

          <button className="btn btn-arcade" onClick={handleEnrichAll}>
            ⚡ 补全信息
          </button>
          <button className="btn" onClick={() => setSettingsOpen(true)} title="设置">
            ⚙ 设置
          </button>

          {/* 任务进度 */}
          <div className="ml-auto">
            <JobProgress
              job={job}
              onCancel={() => gameApi.cancel(job?.id || '')}
              accent="arcade"
            />
          </div>
        </div>

        {/* 详情 + 封面墙 */}
        <div className="flex min-h-0 flex-1 flex-col">
          {/* 上方详情 */}
          <div className="shrink-0 border-b divider" style={{ maxHeight: '45vh' }}>
            <GameDetail game={selectedGame} onUpdated={handleUpdate} onEdit={handleEdit} />
          </div>

          {/* 下方封面墙 */}
          <div className="flex min-h-0 flex-1 overflow-y-auto">
            <div className="flex flex-wrap content-start gap-3 p-3">
              {games.map((game) => (
                <GameCard
                  key={game.key}
                  game={game}
                  scale={store.posterScale}
                  selected={game.key === store.selectedKey}
                  onSelect={handleSelect}
                  onContextMenu={handleContextMenu}
                />
              ))}
            </div>
          </div>
        </div>
      </main>

      {/* 右键菜单 */}
      {contextMenu && (
        <div
          className="fixed z-50 min-w-[10rem] rounded-lg border border-ink-700 bg-ink-800 py-1 shadow-2xl ring-1 ring-black/40"
          style={{ left: contextMenu.x, top: contextMenu.y }}
          onMouseLeave={() => setContextMenu(null)}
        >
          <MenuItem onClick={() => store.selectGame(contextMenu.game.key)}>
            查看详情
          </MenuItem>
          <MenuItem onClick={() => handleEdit(contextMenu.game)}>
            📝 编辑信息
          </MenuItem>
          <MenuItem onClick={() => alert('TODO: 启动游戏')}>
            ▶ 启动游戏
          </MenuItem>
          <MenuItem
            onClick={() => {
              navigator.clipboard.writeText(contextMenu.game.installed_exe || '');
              setContextMenu(null);
            }}
          >
            📁 复制路径
          </MenuItem>
        </div>
      )}

      {contextMenu && (
        <div className="fixed inset-0 z-40" onClick={() => setContextMenu(null)} />
      )}

      {/* 设置对话框 */}
      <GameSettingsDialog open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </div>
  );
}

function MenuItem({
  children,
  onClick,
  className = '',
}: {
  children: React.ReactNode;
  onClick: () => void;
  className?: string;
}) {
  return (
    <button
      className={`flex w-full items-center px-3 py-1.5 text-left text-xs text-ink-200 hover:bg-ink-700 ${className}`}
      onClick={onClick}
    >
      {children}
    </button>
  );
}
