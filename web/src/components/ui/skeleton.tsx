"use client";

/**
 * 6.2：骨架屏组件——数据加载前占位，避免空白 + 布局跳动（CLS）。
 *
 * 用法：
 *   <Skeleton className="h-10 w-full" />                 // 单行
 *   <SkeletonTable rows={5} cols={4} />                  // 表格骨架
 *   <SkeletonCards count={4} className="h-24" />          // 卡片骨架
 */
import * as React from "react";

import { cn } from "@/lib/utils";

function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      data-slot="skeleton"
      className={cn("animate-pulse rounded-lg bg-stone-200/80 dark:bg-stone-700/60", className)}
      {...props}
    />
  );
}

/** 表格骨架：rows 行 × cols 列，行内等宽占位。 */
function SkeletonTable({ rows = 5, cols = 4, className }: { rows?: number; cols?: number; className?: string }) {
  return (
    <div className={cn("space-y-3", className)} role="status" aria-label="加载中">
      {Array.from({ length: rows }).map((_, row) => (
        <div key={row} className="flex gap-3">
          {Array.from({ length: cols }).map((_, col) => (
            <Skeleton key={col} className="h-8 flex-1" />
          ))}
        </div>
      ))}
    </div>
  );
}

/** 卡片骨架：count 个占位卡片。 */
function SkeletonCards({ count = 4, className }: { count?: number; className?: string }) {
  return (
    <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
      {Array.from({ length: count }).map((_, i) => (
        <Skeleton key={i} className={cn("h-24 rounded-xl", className)} />
      ))}
    </div>
  );
}

export { Skeleton, SkeletonTable, SkeletonCards };
