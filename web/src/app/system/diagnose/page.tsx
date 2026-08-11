"use client";

import { useCallback, useEffect, useState } from "react";
import { runDiagnose, getLastDiagnose, type DiagnosticReport } from "@/lib/api";

export default function DiagnosePage() {
  const [report, setReport] = useState<DiagnosticReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const data = await getLastDiagnose();
      if (data.report) setReport(data.report);
    } catch { /* 首次加载无报告 */ }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const handleDiagnose = async () => {
    setLoading(true);
    setError("");
    try {
      const data = await runDiagnose();
      setReport(data);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };

  const statusColor = (s: string) => {
    if (s === "ok") return "text-green-600 dark:text-green-400";
    if (s === "warning") return "text-yellow-600 dark:text-yellow-400";
    return "text-red-600 dark:text-red-400";
  };

  const severityIcon = (sev: string) => {
    if (sev === "critical") return "🔴";
    if (sev === "error") return "❌";
    if (sev === "warning") return "⚠️";
    return "✅";
  };

  return (
    <div className="mx-auto max-w-4xl p-4 sm:p-6">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-xl font-bold">系统诊断</h1>
        <button
          onClick={handleDiagnose}
          disabled={loading}
          className="rounded-lg bg-stone-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-stone-700 disabled:opacity-50 dark:bg-white dark:text-stone-900 dark:hover:bg-stone-200"
        >
          {loading ? "诊断中..." : "运行诊断"}
        </button>
      </div>

      {error && (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-900/20 dark:text-red-400">
          {error}
        </div>
      )}

      {report && (
        <>
          <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <div className="rounded-lg border p-3 dark:border-white/10">
              <div className="text-xs text-stone-500">总检查项</div>
              <div className="text-2xl font-bold">{report.results.length}</div>
            </div>
            <div className="rounded-lg border p-3 dark:border-white/10">
              <div className="text-xs text-green-600">通过</div>
              <div className="text-2xl font-bold text-green-600">{report.summary.ok ?? 0}</div>
            </div>
            <div className="rounded-lg border p-3 dark:border-white/10">
              <div className="text-xs text-yellow-600">警告</div>
              <div className="text-2xl font-bold text-yellow-600">{report.summary.warning ?? 0}</div>
            </div>
            <div className="rounded-lg border p-3 dark:border-white/10">
              <div className="text-xs text-red-600">错误</div>
              <div className="text-2xl font-bold text-red-600">{report.summary.error ?? 0}</div>
            </div>
          </div>

          <div className="mb-4 text-xs text-stone-400">
            耗时: {report.duration_ms}ms
          </div>

          <div className="space-y-2">
            {report.results.map((r, i) => (
              <div key={i} className="rounded-lg border p-3 dark:border-white/10">
                <div className="flex items-center gap-2">
                  <span>{severityIcon(r.severity)}</span>
                  <span className="font-mono text-xs font-medium uppercase text-stone-500">{r.check}</span>
                  <span className={`text-sm font-medium ${statusColor(r.status)}`}>{r.status}</span>
                </div>
                <div className="mt-1 text-sm">{r.message}</div>
                {r.details && Object.keys(r.details).length > 0 && (
                  <pre className="mt-2 overflow-x-auto rounded bg-stone-50 p-2 text-xs dark:bg-stone-900">
                    {JSON.stringify(r.details, null, 2)}
                  </pre>
                )}
              </div>
            ))}
          </div>
        </>
      )}

      {!report && !loading && (
        <div className="rounded-lg border border-dashed p-8 text-center text-stone-400 dark:border-white/10">
          点击"运行诊断"开始检查系统状态
        </div>
      )}
    </div>
  );
}