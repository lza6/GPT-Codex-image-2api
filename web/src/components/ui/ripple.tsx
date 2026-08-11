"use client";

/**
 * Ripple — 波纹点击组件。
 *
 * 用法：
 * ```tsx
 * <Ripple>
 *   <button>点击我</button>
 * </Ripple>
 * ```
 */
import * as React from "react";
import { motion, AnimatePresence } from "motion/react";

import { cn } from "@/lib/utils";

interface Ripple {
  id: number;
  x: number;
  y: number;
  size: number;
  color: string;
}

interface RippleProps {
  /** 波纹颜色（默认当前文本色，半透明） */
  color?: string;
  /** 波纹持续时间（ms，默认 600） */
  duration?: number;
  children: React.ReactNode;
  className?: string;
}

function Ripple({ color = "currentColor", duration = 600, children, className }: RippleProps) {
  const [ripples, setRipples] = React.useState<Ripple[]>([]);
  const idRef = React.useRef(0);
  const containerRef = React.useRef<HTMLDivElement>(null);

  const handleClick = React.useCallback(
    (event: React.MouseEvent<HTMLDivElement>) => {
      const rect = containerRef.current?.getBoundingClientRect();
      if (!rect) return;

      // 计算波纹大小（取容器宽高最大值 * 2）
      const size = Math.max(rect.width, rect.height) * 2;
      const x = event.clientX - rect.left - size / 2;
      const y = event.clientY - rect.top - size / 2;

      idRef.current += 1;
      const newRipple: Ripple = {
        id: idRef.current,
        x,
        y,
        size,
        color,
      };

      setRipples((prev) => [...prev, newRipple]);

      // 自动移除
      setTimeout(() => {
        setRipples((prev) => prev.filter((r) => r.id !== newRipple.id));
      }, duration);
    },
    [color, duration],
  );

  return (
    <div
      ref={containerRef}
      className={cn("relative overflow-hidden", className)}
      onClick={handleClick}
    >
      {children}
      <AnimatePresence>
        {ripples.map((ripple) => (
          <motion.span
            key={ripple.id}
            initial={{ scale: 0, opacity: 0.35 }}
            animate={{ scale: 1, opacity: 0 }}
            exit={{ opacity: 0 }}
            transition={{ duration: duration / 1000, ease: "easeOut" }}
            className="pointer-events-none absolute -translate-x-1/2 -translate-y-1/2 rounded-full"
            style={{
              left: ripple.x + ripple.size / 2,
              top: ripple.y + ripple.size / 2,
              width: ripple.size,
              height: ripple.size,
              backgroundColor: ripple.color,
            }}
          />
        ))}
      </AnimatePresence>
    </div>
  );
}

export { Ripple };