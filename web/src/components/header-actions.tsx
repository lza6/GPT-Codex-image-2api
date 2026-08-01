"use client";

import { ThemeToggle } from "@/components/theme-toggle";
import { VersionReleaseDialog } from "@/components/version-release-dialog";
import { cn } from "@/lib/utils";

export function HeaderActions({ className }: { className?: string }) {
  return (
    <div className={cn("flex items-center gap-2 sm:gap-3", className)}>
      <ThemeToggle />
      <VersionReleaseDialog />
    </div>
  );
}
