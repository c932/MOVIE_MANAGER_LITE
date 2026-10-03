// 游戏墙设置对话框
import { useEffect, useState } from 'react';
import { gameApi } from '../../api/client';
import type { GameSettings } from '../../types/api';

interface Props {
  open: boolean;
  onClose: () => void;
}

export function GameSettingsDialog({ open, onClose }: Props) {
  const [settings, setSettings] = useState<GameSettings | null>(null);
  const [newApiKey, setNewApiKey] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) {
      gameApi.settings().then(setSettings);
      setNewApiKey('');
    }
  }, [open]);

  if (!open || !settings) return null;

  const save = async () => {
    setSaving(true);
    try {
      const payload: Partial<GameSettings> = { ...settings };
      if (newApiKey) {
        (payload as Record<string, unknown>).llm_api_key = newApiKey;
      }
      await gameApi.putSettings(payload);
      onClose();
    } catch (e) {
      alert((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={onClose}>
      <div
        className="max-h-[85vh] w-full max-w-lg overflow-y-auto rounded-2xl bg-ink-800 p-6 shadow-2xl ring-1 ring-ink-700"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="mb-4 text-lg font-semibold text-ink-50">游戏墙设置</h2>

        <div className="space-y-4">
          {/* Excel 路径 */}
          <div>
            <label className="mb-1.5 block text-xs text-ink-300">Excel 清单路径</label>
            <input
              className="input w-full"
              value={settings.excel_path}
              onChange={(e) => setSettings({ ...settings, excel_path: e.target.value })}
            />
          </div>

          {/* 游戏目录 */}
          <div>
            <label className="mb-1.5 block text-xs text-ink-300">游戏目录</label>
            {settings.game_dirs.map((d, i) => (
              <div key={i} className="mb-1.5 flex gap-2">
                <input
                  className="input flex-1"
                  value={d}
                  onChange={(e) => {
                    const dirs = [...settings.game_dirs];
                    dirs[i] = e.target.value;
                    setSettings({ ...settings, game_dirs: dirs });
                  }}
                />
                <button
                  className="btn text-red-400"
                  onClick={() =>
                    setSettings({
                      ...settings,
                      game_dirs: settings.game_dirs.filter((_, j) => j !== i),
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
                setSettings({ ...settings, game_dirs: [...settings.game_dirs, ''] })
              }
            >
              + 添加目录
            </button>
          </div>

          {/* 开关项 */}
          <div className="space-y-2">
            <Toggle
              label="网络功能"
              value={settings.network_enabled}
              onChange={(v) => setSettings({ ...settings, network_enabled: v })}
            />
            <Toggle
              label="Steam 信息补全"
              value={settings.enable_enrichment}
              onChange={(v) => setSettings({ ...settings, enable_enrichment: v })}
            />
            <Toggle
              label="Gamersky 评分抓取"
              value={settings.enable_gamersky_scraper}
              onChange={(v) => setSettings({ ...settings, enable_gamersky_scraper: v })}
            />
            <Toggle
              label="IGN 评分抓取"
              value={settings.enable_ign_scraper}
              onChange={(v) => setSettings({ ...settings, enable_ign_scraper: v })}
            />
            <Toggle
              label="LLM 判定"
              value={settings.llm_enabled}
              onChange={(v) => setSettings({ ...settings, llm_enabled: v })}
            />
          </div>

          {/* LLM 配置 */}
          {settings.llm_enabled && (
            <div className="rounded-lg bg-ink-900 p-3">
              <h3 className="mb-2 text-xs font-medium text-arcade-400">LLM 配置</h3>
              <div className="space-y-2">
                <div>
                  <label className="mb-1 block text-2xs text-ink-400">API Base URL</label>
                  <input
                    className="input w-full"
                    value={settings.llm_base_url}
                    onChange={(e) =>
                      setSettings({ ...settings, llm_base_url: e.target.value })
                    }
                  />
                </div>
                <div>
                  <label className="mb-1 block text-2xs text-ink-400">模型</label>
                  <input
                    className="input w-full"
                    value={settings.llm_model}
                    onChange={(e) =>
                      setSettings({ ...settings, llm_model: e.target.value })
                    }
                  />
                </div>
                <div>
                  <label className="mb-1 block text-2xs text-ink-400">
                    API Key {settings.llm_api_key_set && '（已设置，留空保持不变）'}
                  </label>
                  <input
                    className="input w-full"
                    type="password"
                    placeholder={settings.llm_api_key_set ? '••••••••' : '输入 API Key'}
                    value={newApiKey}
                    onChange={(e) => setNewApiKey(e.target.value)}
                  />
                </div>
              </div>
            </div>
          )}
        </div>

        <div className="mt-6 flex justify-end gap-2">
          <button className="btn" onClick={onClose}>
            取消
          </button>
          <button className="btn btn-arcade" onClick={save} disabled={saving}>
            {saving ? '保存中…' : '保存'}
          </button>
        </div>
      </div>
    </div>
  );
}

function Toggle({
  label,
  value,
  onChange,
}: {
  label: string;
  value: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex cursor-pointer items-center justify-between">
      <span className="text-sm text-ink-200">{label}</span>
      <button
        type="button"
        className={`relative h-5 w-9 rounded-full transition-colors ${
          value ? 'bg-arcade-500' : 'bg-ink-600'
        }`}
        onClick={() => onChange(!value)}
      >
        <span
          className={`absolute top-0.5 h-4 w-4 rounded-full bg-white transition-transform ${
            value ? 'left-4' : 'left-0.5'
          }`}
        />
      </button>
    </label>
  );
}