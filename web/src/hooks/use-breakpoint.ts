"use client";

/**
 * useBreakpoint — 响应式断点检测 Hook。
 *
 * 用法：
 * ```tsx
 * const { isMobile, isTablet, isDesktop, breakpoint } = useBreakpoint();
 * if (isMobile) return <MobileView />;
 * ```
 *
 * 断点：
 * - mobile: < 640px (sm)
 * - tablet: 640px ~ 1023px (md)
 * - desktop: >= 1024px (lg)
 */
import { useCallback, useEffect, useState } from "react";

export type Breakpoint = "mobile" | "tablet" | "desktop";

const QUERIES = {
  mobile: "(max-width: 639px)",
  tablet: "(min-width: 640px) and (max-width: 1023px)",
  desktop: "(min-width: 1024px)",
} as const;

function getBreakpoint(): Breakpoint {
  if (typeof window === "undefined") return "desktop";
  if (window.matchMedia(QUERIES.mobile).matches) return "mobile";
  if (window.matchMedia(QUERIES.tablet).matches) return "tablet";
  return "desktop";
}

export function useBreakpoint() {
  const [breakpoint, setBreakpoint] = useState<Breakpoint>(getBreakpoint);

  useEffect(() => {
    const mqls = Object.entries(QUERIES).map(([key, query]) => {
      const mql = window.matchMedia(query);
      const handler = (e: MediaQueryListEvent) => {
        if (e.matches) setBreakpoint(key as Breakpoint);
      };
      mql.addEventListener("change", handler);
      return { mql, handler };
    });

    return () => {
      for (const { mql, handler } of mqls) {
        mql.removeEventListener("change", handler as (e: MediaQueryListEvent) => void);
      }
    };
  }, []);

  const isMobile = breakpoint === "mobile";
  const isTablet = breakpoint === "tablet";
  const isDesktop = breakpoint === "desktop";

  return { breakpoint, isMobile, isTablet, isDesktop };
}