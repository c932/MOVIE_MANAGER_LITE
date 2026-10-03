import { Link } from 'react-router-dom';

export default function Home() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-ink-900 p-6">
      <div className="w-full max-w-2xl space-y-8">
        <div className="text-center">
          <h1 className="text-3xl font-semibold text-ink-50">媒体墙</h1>
          <p className="mt-2 text-sm text-ink-400">选择要浏览的媒体库</p>
        </div>

        <div className="grid gap-6 sm:grid-cols-2">
          <Link
            to="/movie"
            className="group relative overflow-hidden rounded-2xl bg-ink-800 p-8 transition-all hover:bg-ink-750 hover:shadow-2xl"
          >
            <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-cinema-600 to-cinema-400" />
            <div className="text-4xl mb-4">🎬</div>
            <h2 className="text-xl font-semibold text-ink-50">电影墙</h2>
            <p className="mt-2 text-sm text-ink-400">
              本地电影海报墙，支持 NFO 解析、豆瓣刮削、榜单对比
            </p>
            <div className="mt-4 flex items-center text-sm text-cinema-400 group-hover:text-cinema-300">
              进入 →
            </div>
          </Link>

          <Link
            to="/game"
            className="group relative overflow-hidden rounded-2xl bg-ink-800 p-8 transition-all hover:bg-ink-750 hover:shadow-2xl"
          >
            <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-arcade-600 to-arcade-400" />
            <div className="text-4xl mb-4">🎮</div>
            <h2 className="text-xl font-semibold text-ink-50">游戏墙</h2>
            <p className="mt-2 text-sm text-ink-400">
              本地游戏封面墙，支持 Steam 补全、五档分类、LLM 判定
            </p>
            <div className="mt-4 flex items-center text-sm text-arcade-400 group-hover:text-arcade-300">
              进入 →
            </div>
          </Link>
        </div>

        <div className="text-center text-2xs text-ink-500">
          服务端部署于 Ubuntu · 前端 React + Vite + Tailwind
        </div>
      </div>
    </div>
  );
}
