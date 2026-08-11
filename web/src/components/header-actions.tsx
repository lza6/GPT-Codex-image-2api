"use client";

import { ThemeToggle } from "@/components/theme-toggle";
import { VersionReleaseDialog } from "@/components/version-release-dialog";
import { NotificationCenter } from "@/components/notification-center";
import { cn } from "@/lib/utils";

export function HeaderActions({ className }: { className?: string }) {
  return (
    <div className={cn("flex items-center gap-2 sm:gap-3", className)}>
      <NotificationCenter />
      <ThemeToggle />
      <VersionReleaseDialog />
    </div>
  );
}
