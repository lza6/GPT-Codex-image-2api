"use client";

import { X, Eye, RotateCcw, ListTodo } from "lucide-react";

import type { BatchQueueItem } from "@/store/batch-queue";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ProgressBar } from "@/components/ui/progress-bar";

// ─── 动作名称映射 ───────────────────────────────────────────────

const actionLabels: Record<string, string> = {
  refresh: "刷新",
  relogin: "重新登录",
  evict: "淘汰",
  label: "标记",
  delete: "删除",
  export: "导出",
};

// ─── 状态配置 ───────────────────────────────────────────────────

const statusConfig: Record<
  BatchQueueItem["status"],
  { label: string; color: "success" | "warning" | "danger" | "info" | "default" }
> = {
  queued:    { label: "排队中", color: "info" },
  running:   { label: "运行中", color: "default" },
  completed: { label: "已完成", color: "success" },
  failed:    { label: "失败",   color: "danger" },
  cancelled: { label: "已取消", color: "warning" },
};

const progressColorMap: Record<
  BatchQueueItem["status"],
  "default" | "success" | "warning" | "error"
> = {
  queued:    "default",
  running:   "default",
  completed: "success",
  failed:    "error",
  cancelled: "warning",
};

// ─── Props ──────────────────────────────────────────────────────

interface BatchQueuePanelProps {
  /** 当前活跃队列 */
  queue: BatchQueueItem[];
  /** 中断（取消）任务 */
  onCancel: (id: string) => void;
  /** 查看任务结果 */
  onViewResult: (item: BatchQueueItem) => void;
  /** 重试失败项 */
  onResume?: (item: BatchQueueItem) => void;
  className?: string;
}

// ─── 组件 ───────────────────────────────────────────────────────

export function BatchQueuePanel({
  queue,
  onCancel,
  onViewResult,
  onResume,
  className,
}: BatchQueuePanelProps) {
  if (queue.length === 0) return null;

  return (
    <div
      className={cn(
        "rounded-2xl border border-white/80 bg-white/95 shadow-[0_20px_60px_-28px_rgba(25,33,61,0.18)] backdrop-blur-lg dark:border-white/10 dark:bg-stone-900/95",
        className,
      )}
    >
      {/* 头部 */}
      <div className="flex items-center gap-2 border-b border-stone-100 px-5 py-3.5 dark:border-stone-800/50">
        <ListTodo className="size-4 text-stone-400" />
        <span className="text-sm font-medium text-stone-700 dark:text-stone-200">
          批量操作
        </span>
        <Badge variant="info" className="ml-auto">
          {queue.length} 项
        </Badge>
      </div>

      {/* 任务列表 */}
      <div className="divide-y divide-stone-100 dark:divide-stone-800/50">
        {queue.map((item) => (
          <div
            key={item.id}
            className="flex flex-col gap-2.5 px-5 py-3.5 transition-colors hover:bg-stone-50/50 dark:hover:bg-stone-800/20"
          >
            {/* 第一行：动作名 + 状态 + 操作按钮 */}
            <div className="flex items-center gap-2">
              {/* 动作名 */}
              <span className="truncate text-sm font-medium text-stone-800 dark:text-stone-100">
                {actionLabels[item.action] ?? item.action}
              </span>
              {item.label && (
                <span className="truncate text-xs text-stone-400 dark:text-stone-500">
                  {item.label}
                </span>
              )}

              {/* 状态 Badge */}
              <Badge
                variant={statusConfig[item.status].color}
                className="ml-auto shrink-0"
              >
                {statusConfig[item.status].label}
              </Badge>

              {/* 操作按钮 */}
              {item.status === "running" || item.status === "queued" ? (
                <Button
                  variant="ghost"
                  size="icon"
                  className="size-7 shrink-0 text-stone-400 hover:text-red-500"
                  title="取消"
                  onClick={() => onCancel(item.id)}
                >
                  <X className="size-3.5" />
                </Button>
              ) : (
                <div className="flex shrink-0 gap-1">
                  {item.status === "completed" && (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-7 gap-1 px-2 text-xs text-emerald-600 hover:text-emerald-700 dark:text-emerald-400 dark:hover:text-emerald-300"
                      onClick={() => onViewResult(item)}
                    >
                      <Eye className="size-3.5" />
                      查看结果
                    </Button>
                  )}
                  {item.status === "failed" && (
                    <>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-7 gap-1 px-2 text-xs text-rose-600 hover:text-rose-700 dark:text-rose-400 dark:hover:text-rose-300"
                        onClick={() => onViewResult(item)}
                      >
                        <Eye className="size-3.5" />
                        查看结果
                      </Button>
                      {onResume && (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-7 gap-1 px-2 text-xs text-amber-600 hover:text-amber-700 dark:text-amber-400 dark:hover:text-amber-300"
                          onClick={() => onResume(item)}
                        >
                          <RotateCcw className="size-3.5" />
                          重试
                        </Button>
                      )}
                    </>
                  )}
                  {item.status === "cancelled" && (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-7 gap-1 px-2 text-xs text-stone-500 hover:text-stone-600 dark:hover:text-stone-300"
                      onClick={() => onViewResult(item)}
                    >
                      <Eye className="size-3.5" />
                      查看结果
                    </Button>
                  )}
                </div>
              )}
            </div>

            {/* 进度条 */}
            <div className="flex items-center gap-3">
              <ProgressBar
                value={item.progress}
                indeterminate={item.status === "running" && item.progress === 0}
                color={progressColorMap[item.status]}
                showValue
                size="sm"
                className="flex-1"
              />
              <span className="shrink-0 text-[11px] text-stone-400">
                {Object.keys(item.results).length}/{item.tokens.length}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}