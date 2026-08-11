"use client";

import { useState } from "react";
import { CheckCircle2, XCircle, AlertCircle, ChevronDown, ChevronRight } from "lucide-react";
import { toast } from "sonner";

import type { BatchQueueItem } from "@/store/batch-queue";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

// ─── Props ──────────────────────────────────────────────────────

interface BatchResultDialogProps {
  item: BatchQueueItem | null;
  onClose: () => void;
  onRetry: (failedTokens: string[]) => void;
}

// ─── 组件 ───────────────────────────────────────────────────────

export function BatchResultDialog({ item, onClose, onRetry }: BatchResultDialogProps) {
  const [expanded, setExpanded] = useState(false);

  if (!item) return null;

  // 统计
  const entries = item.tokens.map((token) => ({
    token,
    result: item.results[token],
  }));
  const successCount = entries.filter((e) => e.result?.success === true).length;
  const failCount = entries.filter((e) => e.result?.success === false).length;
  const skipCount = entries.filter((e) => !e.result).length;
  const failedEntries = entries.filter((e) => e.result?.success === false);
  const failedTokens = failedEntries.map((e) => e.token);

  const handleRetry = () => {
    if (failedTokens.length === 0) {
      toast.info("没有失败项需要重试");
      return;
    }
    onRetry(failedTokens);
    toast.success(`已重新提交 ${failedTokens.length} 个失败项`);
    onClose();
  };

  const truncateToken = (token: string, maxLen = 20) => {
    if (token.length <= maxLen) return token;
    return `${token.slice(0, 10)}...${token.slice(-7)}`;
  };

  return (
    <Dialog open={!!item} onOpenChange={() => onClose()}>
      <DialogContent className="w-[min(94vw,540px)] rounded-2xl">
        <DialogHeader>
          <DialogTitle>批量操作结果</DialogTitle>
        </DialogHeader>

        {/* 统计卡片 */}
        <div className="grid grid-cols-3 gap-3">
          <StatCard
            icon={<CheckCircle2 className="size-4 text-emerald-600" />}
            label="成功"
            value={successCount}
            total={item.tokens.length}
            barColor="bg-emerald-500"
          />
          <StatCard
            icon={<XCircle className="size-4 text-rose-600" />}
            label="失败"
            value={failCount}
            total={item.tokens.length}
            barColor="bg-rose-500"
          />
          <StatCard
            icon={<AlertCircle className="size-4 text-stone-400" />}
            label="跳过"
            value={skipCount}
            total={item.tokens.length}
            barColor="bg-stone-300 dark:bg-stone-600"
          />
        </div>

        {/* 失败详情 */}
        {failedEntries.length > 0 && (
          <div className="rounded-xl border border-white/80 bg-white/55 dark:border-white/10 dark:bg-white/5">
            <button
              type="button"
              className="flex w-full items-center gap-2 px-4 py-3 text-sm font-medium text-stone-700 dark:text-stone-200"
              onClick={() => setExpanded(!expanded)}
            >
              {expanded ? (
                <ChevronDown className="size-3.5 text-stone-400" />
              ) : (
                <ChevronRight className="size-3.5 text-stone-400" />
              )}
              失败详情
              <Badge variant="danger" className="ml-auto">
                {failedEntries.length}
              </Badge>
            </button>
            {expanded && (
              <div className="divide-y divide-stone-100 border-t border-stone-100 dark:divide-stone-800/50 dark:border-stone-800/50">
                {failedEntries.map(({ token, result }) => (
                  <div key={token} className="space-y-1 px-4 py-2.5">
                    <div className="truncate text-xs font-mono text-stone-500 dark:text-stone-400">
                      {truncateToken(token)}
                    </div>
                    <div className="text-xs text-rose-600 dark:text-rose-400">
                      {result?.error ?? "未知错误"}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* 操作按钮 */}
        <div className="flex items-center justify-end gap-2">
          {failedTokens.length > 0 && (
            <Button variant="default" size="sm" onClick={handleRetry}>
              重试失败项（{failedTokens.length}）
            </Button>
          )}
          <Button variant="outline" size="sm" onClick={onClose}>
            关闭
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

// ─── 统计卡片子组件 ──────────────────────────────────────────────

function StatCard({
  icon,
  label,
  value,
  total,
  barColor,
}: {
  icon: React.ReactNode;
  label: string;
  value: number;
  total: number;
  barColor: string;
}) {
  const pct = total > 0 ? Math.round((value / total) * 100) : 0;
  return (
    <div className="rounded-xl border border-white/80 bg-white/55 p-3 dark:border-white/10 dark:bg-white/5">
      <div className="flex items-center gap-1.5">
        {icon}
        <span className="text-xs text-stone-500 dark:text-stone-400">{label}</span>
      </div>
      <div className="mt-1 text-lg font-semibold text-stone-950 dark:text-stone-100">
        {value}
        <span className="text-xs font-normal text-stone-400">/{total}</span>
      </div>
      <div className="mt-1.5 h-1 rounded-full bg-stone-100 dark:bg-stone-800">
        <div
          className={cn("h-full rounded-full transition-all", barColor)}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}