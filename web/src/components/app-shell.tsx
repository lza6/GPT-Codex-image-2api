"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { AnimatePresence, motion } from "motion/react";

import { ErrorBoundary } from "@/components/error-boundary";
import { PageTransition } from "@/components/page-transition";
import { ShortcutsDialog } from "@/components/shortcuts-dialog";
import { useKeyboard } from "@/hooks/use-keyboard";
import { getDefaultRouteForRole } from "@/store/auth";
import { getStoredAuthSession, type StoredAuthSession } from "@/lib/auth-session";

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [session, setSession] = useState<StoredAuthSession | null | undefined>(undefined);
  const didLoadRef = useRef(false);

  useEffect(() => {
    if (didLoadRef.current) return;
    didLoadRef.current = true;
    getStoredAuthSession().then(setSession);
  }, []);

  // 快捷键：导航
  const handleNav = useCallback(
    (href: string) => {
      router.push(href);
    },
    [router],
  );

  useKeyboard([
    { key: "1", ctrl: true, handler: () => handleNav("/dashboard"), description: "运维看板" },
    { key: "2", ctrl: true, handler: () => handleNav("/image"), description: "生图" },
    { key: "3", ctrl: true, handler: () => handleNav("/accounts"), description: "号池管理" },
    { key: "4", ctrl: true, handler: () => handleNav("/proxy-pool"), description: "IP 池" },
    { key: "5", ctrl: true, handler: () => handleNav("/image-manager"), description: "图片管理" },
    { key: "6", ctrl: true, handler: () => handleNav("/logs"), description: "日志管理" },
    { key: "7", ctrl: true, handler: () => handleNav("/settings"), description: "设置" },
    {
      key: "r",
      ctrl: true,
      handler: () => window.location.reload(),
      description: "刷新页面",
    },
    {
      key: "k",
      ctrl: true,
      handler: () => {
        // GlobalSearch 自身监听了 Ctrl+K，这里不重复触发
      },
      description: "全局搜索",
    },
  ]);

  return (
    <ErrorBoundary>
      <ShortcutsDialog />
      <PageTransition pathname={pathname}>{children}</PageTransition>
    </ErrorBoundary>
  );
}