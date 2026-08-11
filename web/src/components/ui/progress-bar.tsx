"use client";

/**
 * ProgressBar — 进度条组件。
 *
 * 用法：
 * ```tsx
 * <ProgressBar value={65} />                // 确定进度
 * <ProgressBar indeterminate />             // 不确定进度（加载中）
 * <ProgressBar value={50} label="上传中" />  // 带标签
 * ```
 */
import * as React from "react";
import { motion } from "motion/react";

import { cn } from "@/lib/utils";

interface ProgressBarProps {
  /** 进度值 0-100 */
  value?: number;
  /** 不确定进度模式（加载中动画） */
  indeterminate?: boolean;
  /** 显示进度标签 */
  label?: string;
  /** 显示百分比文本 */
  showValue?: boolean;
  /** 尺寸 */
  size?: "sm" | "md" | "lg";
  /** 颜色主题 */
  color?: "default" | "success" | "warning" | "error";
  className?: string;
}

const sizeMap = {
  sm: { bar: "h-1", text: "text-[10px]" },
  md: { bar: "h-1.5", text: "text-xs" },
  lg: { bar: "h-2.5", text: "text-sm" },
};

const colorMap = {
  default: "bg-stone-950 dark:bg-white",
  success: "bg-emerald-500",
  warning: "bg-amber-500",
  error: "bg-red-500",
};

const bgColorMap = {
  default: "bg-stone-100 dark:bg-stone-700",
  success: "bg-emerald-100 dark:bg-emerald-950/30",
  warning: "bg-amber-100 dark:bg-amber-950/30",
  error: "bg-red-100 dark:bg-red-950/30",
};

function ProgressBar({
  value = 0,
  indeterminate = false,
  label,
  showValue = false,
  size = "md",
  color = "default",
  className,
}: ProgressBarProps) {
  const clampedValue = Math.min(100, Math.max(0, value));

  return (
    <div className={cn("flex flex-col gap-1", className)}>
      {(label || showValue) && (
        <div className="flex items-center justify-between">
          {label && <span className={cn("text-stone-500", sizeMap[size].text)}>{label}</span>}
          {showValue && !indeterminate && (
            <span className={cn("font-medium text-stone-700", sizeMap[size].text)}>{Math.round(clampedValue)}%</span>
          )}
        </div>
      )}
      <div className={cn("w-full overflow-hidden rounded-full", bgColorMap[color], sizeMap[size].bar)} role="progressbar" aria-valuenow={indeterminate ? undefined : clampedValue} aria-valuemin={0} aria-valuemax={100}>
        {indeterminate ? (
          <motion.div
            className={cn("h-full rounded-full", colorMap[color], sizeMap[size].bar)}
            animate={{ x: ["-100%", "200%"] }}
            transition={{ repeat: Infinity, duration: 1.5, ease: "easeInOut" }}
            style={{ width: "50%" }}
          />
        ) : (
          <motion.div
            className={cn("h-full rounded-full transition-all", colorMap[color])}
            initial={{ width: 0 }}
            animate={{ width: `${clampedValue}%` }}
            transition={{ duration: 0.4, ease: "easeOut" }}
          />
        )}
      </div>
    </div>
  );
}

export { ProgressBar };
export type { ProgressBarProps };