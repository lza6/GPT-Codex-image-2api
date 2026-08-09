"use client";

import { useEffect, useState } from "react";
import { Keyboard } from "lucide-react";

import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";

const DEFAULT_SHORTCUTS: { key: string; label: string }[] = [
  { key: "Ctrl+1", label: "运维看板" },
  { key: "Ctrl+2", label: "生图" },
  { key: "Ctrl+3", label: "号池管理" },
  { key: "Ctrl+4", label: "IP 池" },
  { key: "Ctrl+5", label: "图片管理" },
  { key: "Ctrl+6", label: "日志管理" },
  { key: "Ctrl+7", label: "设置" },
  { key: "Ctrl+K", label: "全局搜索" },
  { key: "Ctrl+R", label: "刷新页面" },
  { key: "?", label: "显示快捷键列表" },
];

export function ShortcutsDialog() {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "?" && !e.ctrlKey && !e.metaKey && !e.altKey) {
        // 仅当不在输入框中时触发
        const active = document.activeElement;
        if (active?.matches("input, textarea, select, [contenteditable]")) return;
        e.preventDefault();
        setOpen((prev) => !prev);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  return (
    <>
      <button
        type="button"
        className="rounded-lg p-1.5 text-stone-400 transition hover:bg-stone-100 hover:text-stone-600 dark:hover:bg-white/10 dark:hover:text-stone-300"
        onClick={() => setOpen(true)}
        title="快捷键列表"
      >
        <Keyboard className="size-4" />
      </button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="rounded-2xl sm:max-w-md">
          <DialogHeader>
            <DialogTitle>快捷键</DialogTitle>
            <DialogDescription>全局键盘快捷键，帮助快速导航和操作。</DialogDescription>
          </DialogHeader>
          <div className="space-y-1">
            {DEFAULT_SHORTCUTS.map((item) => (
              <div
                key={item.key}
                className="flex items-center justify-between rounded-lg px-3 py-2 text-sm hover:bg-stone-50 dark:hover:bg-white/5"
              >
                <span className="text-stone-600 dark:text-stone-400">{item.label}</span>
                <kbd className="rounded-md border border-stone-200 bg-stone-50 px-2 py-0.5 text-[11px] font-medium text-stone-500 dark:border-stone-700 dark:bg-stone-800 dark:text-stone-400">
                  {item.key}
                </kbd>
              </div>
            ))}
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}