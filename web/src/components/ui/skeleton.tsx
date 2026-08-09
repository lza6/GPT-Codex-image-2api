"use client";

/**
 * 6.2：骨架屏组件——数据加载前占位，避免空白 + 布局跳动（CLS）。
 *
 * 用法：
 *   <Skeleton className="h-10 w-full" />                 // 单行
 *   <SkeletonTable rows={5} cols={4} />                  // 表格骨架
 *   <SkeletonCards count={4} className="h-24" />          // 卡片骨架
 *   <SkeletonText lines={3} />                            // 文本骨架
 *   <SkeletonAvatar size="md" />                          // 头像骨架
 *   <SkeletonDashboard />                                 // 看板骨架
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

/** 文本骨架：lines 行文本占位，末行宽 60%。 */
function SkeletonText({ lines = 3, className }: { lines?: number; className?: string }) {
  return (
    <div className={cn("space-y-2", className)} role="status" aria-label="加载中">
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton
          key={i}
          className={cn("h-4", i === lines - 1 ? "w-3/5" : "w-full")}
        />
      ))}
    </div>
  );
}

/** 头像骨架：circle/rounded 两种形态，sm/md/lg 三种尺寸。 */
function SkeletonAvatar({
  size = "md",
  shape = "circle",
  className,
}: {
  size?: "sm" | "md" | "lg";
  shape?: "circle" | "rounded";
  className?: string;
}) {
  const sizeMap = { sm: "h-8 w-8", md: "h-10 w-10", lg: "h-14 w-14" };
  return (
    <Skeleton
      className={cn(
        sizeMap[size],
        shape === "circle" ? "rounded-full" : "rounded-lg",
        className,
      )}
      role="status"
      aria-label="加载中"
    />
  );
}

/** 看板骨架：StatCard×4 + 图表 + 表格，完整布局占位。 */
function SkeletonDashboard({ className }: { className?: string }) {
  return (
    <div className={cn("space-y-6", className)} role="status" aria-label="看板加载中">
      {/* 标题 */}
      <Skeleton className="h-8 w-40" />
      {/* 统计卡片 */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="rounded-xl border border-stone-200 bg-white p-4 dark:border-stone-700 dark:bg-stone-900">
            <Skeleton className="mb-2 h-3 w-16" />
            <Skeleton className="h-8 w-20" />
          </div>
        ))}
      </div>
      {/* 图表占位 */}
      <Skeleton className="h-64 w-full rounded-xl" />
      {/* 表格行 */}
      <div className="space-y-2 rounded-xl border border-stone-200 bg-white p-4 dark:border-stone-700 dark:bg-stone-900">
        <Skeleton className="mb-4 h-6 w-32" />
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="flex gap-4">
            <Skeleton className="h-5 flex-1" />
            <Skeleton className="h-5 w-16" />
            <Skeleton className="h-5 w-16" />
            <Skeleton className="h-5 w-20" />
          </div>
        ))}
      </div>
    </div>
  );
}

export { Skeleton, SkeletonTable, SkeletonCards, SkeletonText, SkeletonAvatar, SkeletonDashboard };
