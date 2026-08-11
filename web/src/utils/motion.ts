"use client";

/**
 * 统一动效预设 — 所有组件共享的 framer-motion 动画配置。
 *
 * 用法：
 * ```tsx
 * import { motion } from "motion/react";
 * import { fadeIn, slideUp, scaleIn, stagger } from "@/utils/motion";
 *
 * <motion.div variants={stagger(0.05)} initial="hidden" animate="visible">
 *   <motion.div variants={slideUp}>Item 1</motion.div>
 *   <motion.div variants={slideUp}>Item 2</motion.div>
 * </motion.div>
 * ```
 */
import type { Variants, Transition, TargetAndTransition } from "motion/react";

/** 缓动函数 */
export const easings = {
  /** 标准缓出 */
  easeOut: [0.16, 1, 0.3, 1] as [number, number, number, number],
  /** 缓入缓出 */
  easeInOut: [0.76, 0, 0.24, 1] as [number, number, number, number],
  /** 弹性缓出 */
  spring: { type: "spring" as const, stiffness: 300, damping: 25 },
  /** 轻量弹性 */
  springLight: { type: "spring" as const, stiffness: 200, damping: 20 },
};

/** 默认过渡 */
export const defaultTransition: Transition = {
  duration: 0.25,
  ease: easings.easeOut,
};

/** 淡入 */
export const fadeIn: Variants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: defaultTransition },
};

/** 向上滑入 */
export const slideUp: Variants = {
  hidden: { opacity: 0, y: 12 },
  visible: { opacity: 1, y: 0, transition: defaultTransition },
};

/** 向下滑入 */
export const slideDown: Variants = {
  hidden: { opacity: 0, y: -12 },
  visible: { opacity: 1, y: 0, transition: defaultTransition },
};

/** 缩放进入 */
export const scaleIn: Variants = {
  hidden: { opacity: 0, scale: 0.95 },
  visible: { opacity: 1, scale: 1, transition: defaultTransition },
};

/** 从左侧滑入 */
export const slideLeft: Variants = {
  hidden: { opacity: 0, x: -20 },
  visible: { opacity: 1, x: 0, transition: defaultTransition },
};

/** 从右侧滑入 */
export const slideRight: Variants = {
  hidden: { opacity: 0, x: 20 },
  visible: { opacity: 1, x: 0, transition: defaultTransition },
};

/** 子元素交错入场：父容器用 stagger + 子元素用 slideUp */
export function stagger(delay = 0.05): Variants {
  return {
    hidden: { transition: { staggerChildren: delay } },
    visible: { transition: { staggerChildren: delay } },
  };
}

/** 行展开/折叠动画 */
export const expandCollapse: Variants = {
  collapsed: { height: 0, opacity: 0, overflow: "hidden" },
  expanded: { height: "auto", opacity: 1, transition: defaultTransition },
};

/** 高亮闪烁（成功/错误） */
export function flash(color: "green" | "red"): TargetAndTransition {
  return {
    backgroundColor: color === "green" ? "rgba(34,197,94,0.15)" : "rgba(239,68,68,0.15)",
    transition: { duration: 0.3, ease: easings.easeOut },
  };
}

/** 涟漪效果（从点击位置扩散） */
export function ripple(x: number, y: number): Variants {
  return {
    idle: { scale: 0, opacity: 0.4, x, y },
    active: { scale: 4, opacity: 0, transition: { duration: 0.5, ease: easings.easeOut } },
  };
}