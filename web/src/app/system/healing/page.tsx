"use client";

import { useCallback, useEffect, useState } from "react";
import { getHealingHistory, runHealing, clearHealingHistory, type HealingHistoryItem, type HealingStats } from "@/lib/api";

export default function HealingPage() {
  const [items, setItems] = useState<HealingHistoryItem[]>([]);
  const [stats, setStats] = useState<HealingStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [healing, setHealing] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await getHealingHistory(100);
      setItems(data.items);
      setStats(data.stats);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const handleHeal = async () => {
    setHealing(true);
    try {
      await runHealing();
      await load();
    } finally {
      setHealing(false);
    }
  };

  const handleClear = async () => {
    if (!confirm("确定清除修复历史？")) return;
    await clearHealingHistory();
    setItems([]);
    setStats(null);
  };

  return (
    <div className="mx-auto max-w-4xl p-4 sm:p-6">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-xl font-bold">自动修复</h1>
        <div className="flex gap-2">
          <button
            onClick={handleHeal}
            disabled={healing}
            className="rounded-lg bg-stone-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-stone-700 disabled:opacity-50 dark:bg-white dark:text-stone-900 dark:hover:bg-stone-200"
          >
            {healing ? "修复中..." : "运行修复"}
          </button>
          <button
            onClick={handleClear}
            className="rounded-lg border px-4 py-2 text-sm text-stone-600 transition hover:bg-stone-50 dark:border-white/10 dark:text-stone-400 dark:hover:bg-white/10"
          >
            清除历史
          </button>
        </div>
      </div>

      {stats && (
        <div className="mb-4 grid grid-cols-3 gap-3">
          <div className="rounded-lg border p-3 dark:border-white/10">
            <div className="text-xs text-stone-500">总尝试</div>
            <div className="text-2xl font-bold">{stats.total_attempts}</div>
          </div>
          <div className="rounded-lg border p-3 dark:border-white/10">
            <div className="text-xs text-green-600">成功</div>
            <div className="text-2xl font-bold text-green-600">{stats.success_count}</div>
          </div>
          <div className="rounded-lg border p-3 dark:border-white/10">
            <div className="text-xs text-stone-500">成功率</div>
            <div className="text-2xl font-bold">{stats.success_rate}%</div>
          </div>
        </div>
      )}

      <div className="space-y-2">
        {items.length === 0 && (
          <div className="rounded-lg border border-dashed p-8 text-center text-stone-400 dark:border-white/10">
            暂无修复记录
          </div>
        )}
        {items.map((item, i) => (
          <div key={i} className="rounded-lg border p-3 dark:border-white/10">
            <div className="flex items-center gap-2">
              <span>{item.healed ? "✅" : "❌"}</span>
              <span className="font-mono text-xs text-stone-500">{item.check}</span>
              <span className="text-xs text-stone-400">{new Date(item.ts * 1000).toLocaleString()}</span>
              {item.duration_ms > 0 && (
                <span className="text-xs text-stone-400">{item.duration_ms}ms</span>
              )}
            </div>
            <div className="mt-1 text-sm">{item.issue_message}</div>
            <div className="mt-0.5 text-xs text-stone-500">{item.detail}</div>
          </div>
        ))}
      </div>
    </div>
  );
}