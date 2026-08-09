"use client";

import { type ReactNode } from "react";
import { Inbox } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type EmptyStateProps = {
  icon?: ReactNode;
  title: string;
  description?: string;
  action?: {
    label: string;
    onClick: () => void;
  };
  className?: string;
};

export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-4 px-6 py-16 text-center",
        className,
      )}
    >
      <div className="flex size-14 items-center justify-center rounded-2xl bg-stone-100 text-stone-400 dark:bg-stone-800/50 dark:text-stone-500">
        {icon ?? <Inbox className="size-6" />}
      </div>
      <div className="max-w-xs space-y-1.5">
        <p className="text-sm font-medium text-stone-700 dark:text-stone-200">
          {title}
        </p>
        {description && (
          <p className="text-xs leading-relaxed text-stone-400 dark:text-stone-500">
            {description}
          </p>
        )}
      </div>
      {action && (
        <Button variant="outline" size="sm" onClick={action.onClick}>
          {action.label}
        </Button>
      )}
    </div>
  );
}