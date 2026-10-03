// 电影墙设置对话框
import { useEffect, useState } from 'react';
import { movieApi } from '../../api/client';
import type { MovieSettings } from '../../types/api';

interface Props {
  open: boolean;
  onClose: () => void;
}

export function MovieSettingsDialog({ open, onClose }: Props) {
  const [settings, setSettings] = useState<MovieSettings | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) movieApi.settings().then(setSettings);
  }, [open]);

  if (!open || !settings) return null;

  const save = async () => {
    setSaving(true);
    try {
      await movieApi.putSettings(settings);
      onClose();
    } catch (e) {
      alert((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const updatePath = (i: number, value: string) => {
    const paths = [...settings.movie_paths];
    paths[i] = value;
    setSettings({ ...settings, movie_paths: paths });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={onClose}>
      <div
        className="w-full max-w-lg rounded-2xl bg-ink-800 p-6 shadow-2xl ring-1 ring-ink-700"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="mb-4 text-lg font-semibold text-ink-50">设置</h2>

        <div className="space-y-4">
          {/* 媒体库路径 */}
          <div>
            <label className="mb-1.5 block text-xs text-ink-300">媒体库路径</label>
            {settings.movie_paths.map((p, i) => (
              <div key={i} className="mb-1.5 flex gap-2">
                <input
                  className="input flex-1"
                  value={p}
                  onChange={(e) => updatePath(i, e.target.value)}
                />
                <button
                  className="btn text-red-400"
                  onClick={() =>
                    setSettings({
                      ...settings,
                      movie_paths: settings.movie_paths.filter((_, j) => j !== i),
                    })
                  }
                >
                  ✕
                </button>
              </div>
            ))}
            <button
              className="btn mt-1"
              onClick={() =>
                setSettings({ ...settings, movie_paths: [...settings.movie_paths, ''] })
              }
            >
              + 添加路径
            </button>
          </div>

          {/* 黑名单 */}
          <div>
            <label className="mb-1.5 block text-xs text-ink-300">黑名单文件夹（逗号分隔）</label>
            <input
              className="input w-full"
              value={settings.blacklist_folders.join(', ')}
              onChange={(e) =>
                setSettings({
                  ...settings,
                  blacklist_folders: e.target.value.split(',').map((s) => s.trim()).filter(Boolean),
                })
              }
            />
          </div>

          <div>
            <label className="mb-1.5 block text-xs text-ink-300">黑名单文件名正则（逗号分隔）</label>
            <input
              className="input w-full"
              value={settings.blacklist_patterns.join(', ')}
              onChange={(e) =>
                setSettings({
                  ...settings,
                  blacklist_patterns: e.target.value.split(',').map((s) => s.trim()).filter(Boolean),
                })
              }
            />
          </div>

          {/* 海报尺寸 */}
          <div className="flex gap-4">
            <div>
              <label className="mb-1.5 block text-xs text-ink-300">海报宽</label>
              <input
                type="number"
                className="input w-24"
                value={settings.poster_width}
                onChange={(e) =>
                  setSettings({ ...settings, poster_width: parseInt(e.target.value) || 200 })
                }
              />
            </div>
            <div>
              <label className="mb-1.5 block text-xs text-ink-300">海报高</label>
              <input
                type="number"
                className="input w-24"
                value={settings.poster_height}
                onChange={(e) =>
                  setSettings({ ...settings, poster_height: parseInt(e.target.value) || 300 })
                }
              />
            </div>
            <div>
              <label className="mb-1.5 block text-xs text-ink-300">网格列数</label>
              <input
                type="number"
                className="input w-24"
                value={settings.grid_columns}
                onChange={(e) =>
                  setSettings({ ...settings, grid_columns: parseInt(e.target.value) || 5 })
                }
              />
            </div>
          </div>
        </div>

        <div className="mt-6 flex justify-end gap-2">
          <button className="btn" onClick={onClose}>
            取消
          </button>
          <button className="btn btn-primary" onClick={save} disabled={saving}>
            {saving ? '保存中…' : '保存'}
          </button>
        </div>
      </div>
    </div>
  );
}