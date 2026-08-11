"use client";

import { useEffect, useState } from "react";
import {
  RefreshCw,
  LogIn,
  XCircle,
  Tag,
  Trash2,
  Download,
  History,
  Clock,
  ChevronRight,
  CheckCircle2,
  AlertCircle,
} from "lucide-react";
import { toast } from "sonner";

import type { BatchAction, BatchQueueItem } from "@/store/batch-queue";
import { getAllHistory, clearHistory, resume } from "@/store/batch-queue";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { BatchResultDialog } from "./batch-result-dialog";

// ─── 动作图标映射 ───────────────────────────────────────────────

const actionIcons: Record<BatchAction, React.ReactNode> = {
  refresh: <RefreshCw className="size-4" />,
  relogin: <LogIn className="size-4" />,
  evict: <XCircle className="size-4" />,
  label: <Tag className="size-4" />,
  delete: <Trash2 className="size-4" />,
  export: <Download className="size-4" />,
};

const actionLabels: Record<string, string> = {
  refresh: "刷新",
  relogin: "重新登录",
  evict: "淘汰",
  label: "标记",
  delete: "删除",
  export: "导出",
};

// ─── 时间格式化 ─────────────────────────────────────────────────

function formatTime(iso: string): string {
  const now = Date.now();
  const diff = now - new Date(iso).getTime();
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return "刚刚";
  if (minutes < 60) return `${minutes} 分钟前`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} 小时前`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days} 天前`;
  return new Date(iso).toLocaleDateString("zh-CN");
}

// ─── Props ──────────────────────────────────────────────────────

interface BatchHistoryDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

// ─── 组件 ───────────────────────────────────────────────────────

export function BatchHistoryDialog({ open, onOpenChange }: BatchHistoryDialogProps) {
  const [history, setHistory] = useState<BatchQueueItem[]>([]);
  const [viewItem, setViewItem] = useState<BatchQueueItem | null>(null);

  // 打开时刷新历史列表
  useEffect(() => {
    if (open) {
      setHistory(getAllHistory());
    }
  }, [open]);

  const handleClear = () => {
    clearHistory();
    setHistory([]);
    toast.success("历史记录已清空");
  };

  const handleRetry = (failedTokens: string[]) => {
    if (!viewItem) return;
    resume(viewItem.id, failedTokens);
    setViewItem(null);
    onOpenChange(false);
  };

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="w-[min(94vw,600px)] rounded-2xl">
          <DialogHeader>
            <DialogTitle>
              <div className="flex items-center gap-2">
                <History className="size-5 text-stone-400" />
                <span>批量操作历史</span>
              </div>
            </DialogTitle>
          </DialogHeader>

          {/* 清空按钮 */}
          {history.length > 0 && (
            <div className="flex justify-end">
              <Button
                variant="ghost"
                size="sm"
                className="h-7 gap-1.5 px-2 text-xs text-stone-500 hover:text-red-600 dark:text-stone-400 dark:hover:text-red-400"
                onClick={handleClear}
              >
                <Trash2 className="size-3.5" />
                清空历史
              </Button>
            </div>
          )}

          {/* 列表 / 空状态 */}
          {history.length === 0 ? (
            <div className="flex flex-col items-center gap-3 py-16 text-stone-400 dark:text-stone-500">
              <History className="size-10" />
              <span className="text-sm">暂无历史记录</span>
            </div>
          ) : (
            <div className="max-h-[420px] overflow-y-auto -mx-1">
              <div className="divide-y divide-stone-100 dark:divide-stone-800/50">
                {history.map((item) => {
                  const results = Object.values(item.results);
                  const successCount = results.filter((r) => r.success).length;
                  const failCount = results.filter((r) => !r.success).length;
                  const skipCount = item.tokens.length - successCount - failCount;

                  return (
                    <button
                      key={item.id}
                      type="button"
                      className="flex w-full items-center gap-3 px-1 py-3 text-left transition-colors hover:bg-stone-50/50 dark:hover:bg-stone-800/20"
                      onClick={() => setViewItem(item)}
                    >
                      {/* 动作图标 */}
                      <div className="flex size-9 shrink-0 items-center justify-center rounded-full bg-stone-100 text-stone-500 dark:bg-stone-800 dark:text-stone-400">
                        {actionIcons[item.action] ?? <History className="size-4" />}
                      </div>

                      {/* 中间内容 */}
                      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                        <div className="flex items-center gap-2">
                          <span className="truncate text-sm font-medium text-stone-800 dark:text-stone-100">
                            {actionLabels[item.action] ?? item.action}
                          </span>
                          {item.label && (
                            <span className="truncate text-xs text-stone-400">{item.label}</span>
                          )}
                        </div>
                        <div className="flex items-center gap-2 text-xs text-stone-400">
                          <Clock className="size-3" />
                          <span>{formatTime(item.createdAt)}</span>
                          <span className="text-stone-300">·</span>
                          <span>{item.tokens.length} 项</span>
                        </div>
                      </div>

                      {/* 右侧统计 */}
                      <div className="flex shrink-0 items-center gap-2.5">
                        <div className="flex items-center gap-1.5">
                          {successCount > 0 && (
                            <span className="flex items-center gap-0.5 text-xs text-emerald-600">
                              <CheckCircle2 className="size-3" />
                              {successCount}
                            </span>
                          )}
                          {failCount > 0 && (
                            <span className="flex items-center gap-0.5 text-xs text-rose-600">
                              <XCircle className="size-3" />
                              {failCount}
                            </span>
                          )}
                          {skipCount > 0 && (
                            <span className="flex items-center gap-0.5 text-xs text-stone-400">
                              <AlertCircle className="size-3" />
                              {skipCount}
                            </span>
                          )}
                        </div>
                        <ChevronRight className="size-4 text-stone-300 dark:text-stone-600" />
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* 详情弹窗 — 复用 BatchResultDialog */}
      <BatchResultDialog
        item={viewItem}
        onClose={() => setViewItem(null)}
        onRetry={handleRetry}
      />
    </>
  );
}