"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, Menu, PanelLeftClose, PanelLeft } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";

import { HeaderActions } from "@/components/header-actions";
import { Sheet, SheetClose, SheetContent, SheetFooter, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { ShortcutsDialog } from "@/components/shortcuts-dialog";
import { getValidatedAuthSession } from "@/lib/auth-session";
import { cn } from "@/lib/utils";
import { clearStoredAuthSession, type StoredAuthSession } from "@/store/auth";

const adminNavItems = [
  { href: "/dashboard", label: "运维看板" },
  { href: "/image", label: "生图" },
  { href: "/accounts", label: "号池管理" },
  { href: "/proxy-pool", label: "IP 池" },
  { href: "/image-manager", label: "图片管理" },
  { href: "/logs", label: "日志管理" },
  { href: "/debug", label: "调试" },
  { href: "/settings", label: "设置" },
];

const userNavItems = [{ href: "/image", label: "画图" }];

/** 面包屑：根据 pathname 生成路径片段 */
function Breadcrumbs({ pathname, navItems }: { pathname: string; navItems: { href: string; label: string }[] }) {
  if (pathname === "/login") return null;

  const segments = pathname.split("/").filter(Boolean);
  const currentNav = navItems.find((item) => item.href === pathname);

  // 首页不看面包屑
  if (segments.length <= 1 && currentNav) return null;

  return (
    <nav className="flex items-center gap-1.5 text-xs text-stone-400 dark:text-stone-500" aria-label="面包屑导航">
      <Link href="/" className="transition hover:text-stone-600 dark:hover:text-stone-300">
        首页
      </Link>
      {segments.map((seg, i) => {
        const href = "/" + segments.slice(0, i + 1).join("/");
        const matchedNav = navItems.find((item) => item.href === href);
        const label = matchedNav?.label ?? seg;
        const isLast = i === segments.length - 1;
        return (
          <span key={href} className="flex items-center gap-1.5">
            <span className="text-stone-300 dark:text-stone-600">/</span>
            {isLast ? (
              <span className="font-medium text-stone-600 dark:text-stone-300">{label}</span>
            ) : (
              <Link href={href} className="transition hover:text-stone-600 dark:hover:text-stone-300">
                {label}
              </Link>
            )}
          </span>
        );
      })}
    </nav>
  );
}

export function TopNav() {
  const pathname = usePathname();
  const router = useRouter();
  const [session, setSession] = useState<StoredAuthSession | null | undefined>(undefined);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  useEffect(() => {
    let active = true;

    const load = async () => {
      if (pathname === "/login") {
        if (!active) return;
        setSession(null);
        return;
      }

      const storedSession = await getValidatedAuthSession();
      if (!active) return;
      setSession(storedSession);
    };

    void load();
    return () => {
      active = false;
    };
  }, [pathname]);

  const handleLogout = useCallback(async () => {
    await clearStoredAuthSession();
    router.replace("/login");
  }, [router]);

  if (pathname === "/login" || session === undefined || !session) {
    return null;
  }

  const navItems = session.role === "admin" ? adminNavItems : userNavItems;
  const roleLabel = session.role === "admin" ? "管理员" : "普通用户";
  const displayName = session.name.trim() || roleLabel;

  const isActive = (href: string) => pathname === href;
  const itemClass = (active: boolean) =>
    cn(
      "flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition",
      active
        ? "bg-stone-950 text-white dark:bg-white dark:text-stone-950"
        : "text-stone-600 hover:bg-stone-100 hover:text-stone-950 dark:text-stone-300 dark:hover:bg-white/10 dark:hover:text-white",
    );

  return (
    <header className="border-b border-stone-100/50 dark:border-white/10">
      <div className="flex min-h-12 flex-col gap-1 px-3 py-2 sm:h-12 sm:flex-row sm:items-center sm:justify-between sm:gap-3 sm:px-6 sm:py-0">
        <div className="flex items-center justify-between gap-2 sm:justify-start sm:gap-3">
          {/* 移动端 Sheet 触发 */}
          <Sheet>
            <SheetTrigger className="inline-flex size-8 items-center justify-center text-stone-700 transition hover:text-stone-950 sm:hidden dark:text-stone-200 dark:hover:text-white">
              <Menu className="size-4" />
              <span className="sr-only">打开导航</span>
            </SheetTrigger>
            <SheetContent side="left">
              <SheetHeader>
                <SheetTitle>chatgpt2api</SheetTitle>
                <span className="text-xs text-stone-500 dark:text-stone-400">{roleLabel} · {displayName}</span>
              </SheetHeader>
              <nav className="mt-8 flex flex-col gap-1">
                {navItems.map((item) => (
                  <SheetClose asChild key={item.href}>
                    <Link href={item.href} className={itemClass(isActive(item.href))}>{item.label}</Link>
                  </SheetClose>
                ))}
              </nav>
              <SheetFooter>
                <button
                  type="button"
                  className="rounded-xl border border-stone-200 px-3 py-2.5 text-left text-sm font-medium text-stone-500 transition hover:text-stone-950 dark:border-white/10 dark:text-stone-300 dark:hover:text-white"
                  onClick={() => void handleLogout()}
                >
                  退出
                </button>
              </SheetFooter>
            </SheetContent>
          </Sheet>

          {/* Logo */}
          <Link
            href="/image"
            className="shrink-0 py-1 text-[15px] font-bold tracking-tight text-stone-950 transition hover:text-stone-700 dark:text-stone-50 dark:hover:text-white"
          >
            chatgpt2api
          </Link>

          {/* 桌面端侧边栏折叠按钮 */}
          <button
            type="button"
            className="hidden size-8 items-center justify-center rounded-lg text-stone-400 transition hover:bg-stone-100 hover:text-stone-700 sm:inline-flex dark:hover:bg-white/10 dark:hover:text-stone-300"
            onClick={() => setSidebarCollapsed((prev) => !prev)}
            title={sidebarCollapsed ? "展开侧边栏" : "折叠侧边栏"}
          >
            {sidebarCollapsed ? <PanelLeft className="size-4" /> : <PanelLeftClose className="size-4" />}
          </button>

          <HeaderActions className="ml-auto sm:hidden" />
        </div>

        {/* 桌面端导航栏 */}
        <nav className="hide-scrollbar -mx-1 hidden min-w-0 flex-1 gap-1 overflow-x-auto px-1 sm:mx-0 sm:flex sm:justify-center sm:gap-8 sm:overflow-visible sm:px-0">
          {navItems.map((item) => {
            const active = isActive(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "relative shrink-0 whitespace-nowrap rounded-full px-2.5 py-1 text-[13px] font-medium transition sm:rounded-none sm:px-0 sm:text-[15px]",
                  active
                    ? "bg-stone-950 text-white sm:bg-transparent sm:font-semibold sm:text-stone-950 dark:bg-white dark:text-stone-950 dark:sm:bg-transparent dark:sm:text-white"
                    : "text-stone-500 hover:text-stone-900 dark:text-stone-400 dark:hover:text-stone-100",
                )}
              >
                {item.label}
                {active ? <span className="absolute inset-x-0 -bottom-[1px] hidden h-0.5 bg-stone-950 dark:bg-white sm:block" /> : null}
              </Link>
            );
          })}
        </nav>

        <div className="hidden items-center justify-end gap-2 sm:flex sm:gap-3">
          <ShortcutsDialog />
          <HeaderActions />
          <span className="hidden rounded-md bg-stone-100 px-2 py-1 text-[10px] font-medium text-stone-500 dark:bg-white/8 dark:text-stone-300 sm:inline-block sm:text-[11px]">
            {roleLabel} · {displayName}
          </span>
          <button
            type="button"
            className="py-1 text-xs text-stone-400 transition hover:text-stone-700 dark:text-stone-500 dark:hover:text-stone-200 sm:text-sm"
            onClick={() => void handleLogout()}
          >
            退出
          </button>
        </div>
      </div>

      {/* 面包屑导航 */}
      <div className="hidden px-6 pb-1.5 sm:block">
        <Breadcrumbs pathname={pathname} navItems={navItems} />
      </div>

      {/* 桌面端可折叠侧边栏 */}
      {!sidebarCollapsed && (
        <aside className="hidden border-r border-stone-100/50 sm:block dark:border-white/10">
          <nav className="flex flex-col gap-0.5 px-3 py-2">
            {navItems.map((item) => {
              const active = isActive(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={cn(
                    "flex items-center gap-2 rounded-lg px-3 py-1.5 text-sm transition",
                    active
                      ? "bg-stone-100 font-medium text-stone-900 dark:bg-white/10 dark:text-white"
                      : "text-stone-500 hover:text-stone-900 dark:text-stone-400 dark:hover:text-white",
                  )}
                >
                  <span className={cn("size-1.5 rounded-full", active ? "bg-stone-900 dark:bg-white" : "bg-transparent")} />
                  {item.label}
                </Link>
              );
            })}
          </nav>
        </aside>
      )}
    </header>
  );
}