// 电影墙设置对话框
import { useEffect, useState } from 'react';
import { movieApi } from '../../api/client';
import type { MovieSettings } from '../../types/api';
import { Modal } from '../Modal';
import { NASSettingsPanel } from './NASSettingsPanel';

interface Props {
  open: boolean;
  onClose: () => void;
  onNasChanged?: () => void;
}

export function MovieSettingsDialog({ open, onClose, onNasChanged }: Props) {
  const [settings, setSettings] = useState<MovieSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    if (open) movieApi.settings().then(value => { if (active) setSettings(value); }).catch(e => { if (active) setError((e as Error).message); });
    return () => { active = false; };
  }, [open]);

  if (!open) return null;
  if (!settings) return <Modal title="后端设置" onClose={onClose}><p role={error ? 'alert' : 'status'}>{error || '正在读取后端设置…'}</p></Modal>;

  const save = async () => {
    setSaving(true);
    try {
      await movieApi.putSettings(settings);
      onClose();
    } catch (e) {
      setError((e as Error).message);
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
    <Modal title="后端设置" onClose={() => !saving && onClose()}>
        <p className="mb-4 text-sm text-ink-300">网页直接使用共享数据库。NAS 登录与媒体库目录在下方分别保存；连接后关闭设置，点击“扫描 NAS”开始扫描。</p>
        {error && <p role="alert" className="mb-3 text-red-400">{error}</p>}
        <NASSettingsPanel onPathsChanged={paths => setSettings(value => value ? {...value, movie_paths: paths} : value)} onChanged={() => onNasChanged?.()} />

        <div className="space-y-4">
          {/* 媒体库路径 */}
          <details>
            <summary className="mb-2 cursor-pointer text-sm text-ink-300">高级：NUC 本地媒体目录</summary>
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
          </details>

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
            {saving ? '保存中…' : '保存显示与过滤设置'}
          </button>
        </div>
    </Modal>
  );
}
