"use client";

import { memo } from "react";
import type { ComponentProps } from "react";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Ban,
  CheckCircle2,
  CircleAlert,
  CircleOff,
  Copy,
  History,
  Pencil,
  RefreshCw,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";
import { copyText } from "@/lib/clipboard";
import { cn } from "@/lib/utils";
import type { Account, AccountColumnVisibility } from "@/lib/api";

// ---- Constants ----

type AccountStatus = "正常" | "限流" | "异常" | "禁用";

const statusMeta: Record<
  AccountStatus,
  { icon: typeof CheckCircle2; badge: ComponentProps<typeof Badge>["variant"] }
> = {
  正常: { icon: CheckCircle2, badge: "success" },
  限流: { icon: CircleAlert, badge: "warning" },
  异常: { icon: CircleOff, badge: "danger" },
  禁用: { icon: Ban, badge: "secondary" },
};

// ---- Helpers ----

function maskToken(token?: string) {
  if (!token) return "—";
  if (token.length <= 18) return token;
  return `${token.slice(0, 16)}...${token.slice(-8)}`;
}

function formatQuota(account: Account) {
  return String(Math.max(0, account.quota));
}

function formatRestoreAt(value?: string | null) {
  if (!value) {
    return { absolute: "—", relative: "" };
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return { absolute: value, relative: "" };
  }
  const diffMs = Math.max(0, date.getTime() - Date.now());
  const totalHours = Math.ceil(diffMs / (1000 * 60 * 60));
  const days = Math.floor(totalHours / 24);
  const hours = totalHours % 24;
  const relative = diffMs > 0 ? `剩余 ${days}d ${hours}h` : "已到恢复时间";
  const pad = (num: number) => String(num).padStart(2, "0");
  const absolute = `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(
    date.getHours(),
  )}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
  return { absolute, relative };
}

export function displayAccountType(account: Account) {
  return account.type || "Free";
}

function displayAccountSource(account: Account) {
  const source = String(account.source_type || "").trim().toLowerCase();
  if (!source) return "web";
  if (source === "web") return "web";
  return source;
}

// ---- Component ----

interface AccountTableRowProps {
  account: Account;
  selected: boolean;
  circuitBreakers: Record<string, { state: string; recover_in_seconds: number }>;
  refreshingTokens: Set<string>;
  isRefreshing: boolean;
  isDeleting: boolean;
  isUpdating: boolean;
  onToggleSelect: (token: string, checked: boolean, event: React.MouseEvent) => void;
  onEdit: (account: Account) => void;
  onTimeline: (account: Account) => void;
  onRefresh: (token: string) => void;
  onDelete: (token: string) => void;
  onClick: (account: Account) => void;
  columnVisibility: AccountColumnVisibility;
}

export const AccountTableRow = memo(function AccountTableRow({
  account,
  selected,
  circuitBreakers,
  refreshingTokens,
  isRefreshing,
  isDeleting,
  isUpdating,
  onToggleSelect,
  onEdit,
  onTimeline,
  onRefresh,
  onDelete,
  onClick,
  columnVisibility,
}: AccountTableRowProps) {
  const status = statusMeta[account.status];
  const StatusIcon = status.icon;

  return (
    <div
      className="flex border-b border-stone-100/80 text-sm text-stone-600 transition-colors hover:bg-stone-50/70 cursor-pointer"
      style={{ height: 60, minHeight: 60 }}
      onClick={() => onClick(account)}
    >
      {/* Checkbox */}
      <div
        className="flex w-12 shrink-0 items-center justify-center px-4"
        onClick={(e) => {
          e.stopPropagation();
          onToggleSelect(account.access_token, !selected, e);
        }}
      >
        <Checkbox checked={selected} className="pointer-events-none" />
      </div>

      {/* Token */}
      <div className="flex w-56 shrink-0 items-center px-4">
        <div className="flex items-center gap-2">
          <span className="font-medium tracking-tight text-stone-700">
            {maskToken(account.access_token)}
          </span>
          <button
            type="button"
            className="rounded-lg p-1 text-stone-400 transition hover:bg-stone-100 hover:text-stone-700"
            onClick={(e) => {
              e.stopPropagation();
              void copyText(account.access_token);
              toast.success("token 已复制");
            }}
          >
            <Copy className="size-4" />
          </button>
        </div>
      </div>

      {/* Type */}
      {columnVisibility.type !== false && (
        <div className="flex w-28 shrink-0 items-center px-4">
          <Badge variant="secondary" className="rounded-md bg-stone-100 text-stone-700">
            {displayAccountType(account)}
          </Badge>
        </div>
      )}

      {/* Source */}
      <div className="flex w-24 shrink-0 items-center px-4">
        <Badge variant="outline" className="rounded-md border-stone-200 text-stone-600">
          {displayAccountSource(account)}
        </Badge>
      </div>

      {/* Status */}
      {columnVisibility.status !== false && (
        <div className="flex w-24 shrink-0 items-center px-4">
          <Badge
            variant={status.badge}
            className="inline-flex items-center gap-1 rounded-md px-2 py-1"
          >
            <StatusIcon className="size-3.5" />
            {account.status}
          </Badge>
        </div>
      )}

      {/* Lifetime risk */}
      {columnVisibility.lifetime_risk !== false && (
        <div className="flex w-24 shrink-0 items-center px-4">
          <Badge
            className={`rounded-md ${
              (
                {
                  low: "bg-emerald-100 text-emerald-700",
                  medium: "bg-amber-100 text-amber-700",
                  high: "bg-orange-100 text-orange-700",
                  critical: "bg-rose-100 text-rose-700",
                } as Record<string, string>
              )[account.lifetime_risk ?? "low"] ?? "bg-emerald-100 text-emerald-700"
            }`}
          >
            {({ low: "健康", medium: "关注", high: "偏高", critical: "濒危" } as Record<string, string>)[
              account.lifetime_risk ?? "low"
            ] ?? "健康"}
            {account.lifetime_eta_days != null ? ` · ${account.lifetime_eta_days}d` : ""}
          </Badge>
        </div>
      )}

      {/* Circuit breaker */}
      <div className="flex w-24 shrink-0 items-center px-4">
        {(() => {
          const breaker = circuitBreakers[account.access_token.slice(-8)];
          if (!breaker) {
            return <span className="text-xs text-stone-300">正常</span>;
          }
          const isOpen = breaker.state === "open";
          return (
            <Badge
              variant={isOpen ? "danger" : "warning"}
              className="rounded-md"
              title={
                isOpen
                  ? `上游连续失败已熔断，${Math.round(breaker.recover_in_seconds)}s 后尝试恢复`
                  : "熔断器半开试探中"
              }
            >
              {isOpen ? "熔断中" : "半开"}
            </Badge>
          );
        })()}
      </div>

      {/* Email + label */}
      {columnVisibility.email !== false && (
        <div className="flex w-56 shrink-0 items-center gap-1 px-4">
          <div className="text-xs leading-5 text-stone-500">{account.email ?? "—"}</div>
          {account.label ? (
            <Badge variant="outline" className="rounded-md px-1.5 py-0 text-[10px] text-violet-600">
              {account.label}
            </Badge>
          ) : null}
        </div>
      )}

      {/* Created at */}
      {columnVisibility.created_at !== false && (
        <div className="flex w-32 shrink-0 items-center px-4 text-xs leading-5 text-stone-500">
          {(() => {
            const raw = account.created_at;
            if (!raw) return "—";
            try {
              const d = new Date(raw + "Z");
              if (isNaN(d.getTime())) return String(raw).slice(0, 10);
              return d.toLocaleDateString("zh-CN", {
                month: "2-digit",
                day: "2-digit",
                hour: "2-digit",
                minute: "2-digit",
              });
            } catch {
              return String(raw).slice(0, 10);
            }
          })()}
        </div>
      )}

      {/* Quota */}
      {columnVisibility.quota !== false && (
        <div className="flex w-24 shrink-0 items-center px-4">
          <Badge variant="info" className="rounded-md">
            {formatQuota(account)}
          </Badge>
        </div>
      )}

      {/* Restore at */}
      <div className="flex w-40 shrink-0 items-center px-4 text-xs leading-5 text-stone-500">
        {(() => {
          const restore = formatRestoreAt(account.restore_at);
          return (
            <div className="space-y-0.5">
              {restore.relative ? (
                <div className="font-medium text-stone-700">{restore.relative}</div>
              ) : null}
              <div>{restore.absolute}</div>
            </div>
          );
        })()}
      </div>

      {/* Image inflight */}
      {columnVisibility.image_inflight !== false && (
        <div className="flex w-18 shrink-0 items-center px-4">
          {(() => {
            const inflight = account.image_inflight ?? 0;
            return (
              <span
                className={inflight > 0 ? "font-semibold text-amber-600" : "text-stone-400"}
                title={
                  inflight > 0
                    ? "当前正在生成的图片数。号池空闲时此值持续 > 0，说明并发槽位泄漏、该账号已被静默排除出调度"
                    : "当前无在途生图任务"
                }
              >
                {inflight}
              </span>
            );
          })()}
        </div>
      )}

      {/* Success */}
      {columnVisibility.success !== false && (
        <div className="flex w-18 shrink-0 items-center px-4 text-stone-500">{account.success}</div>
      )}

      {/* Fail */}
      {columnVisibility.fail !== false && (
        <div className="flex w-18 shrink-0 items-center px-4 text-stone-500">{account.fail}</div>
      )}

      {/* Error reason */}
      {columnVisibility.last_refresh_error !== false && (
        <div className="flex w-48 shrink-0 items-center px-4">
          {account.status === "异常" ? (
            <div
              className="max-w-[200px] truncate text-xs text-rose-600"
              title={`${account.last_refresh_error ?? "未知错误"}\n次数: ${account.invalid_count ?? 0}\n时间: ${
                account.last_refresh_error_at ?? account.last_invalid_at ?? "—"
              }`}
            >
              {account.last_refresh_error || account.last_token_refresh_error || "未知错误"}
            </div>
          ) : (
            <span className="text-stone-300">—</span>
          )}
        </div>
      )}

      {/* Actions */}
      <div className="flex w-24 shrink-0 items-center px-4">
        <div className="flex items-center gap-1 text-stone-400" onClick={(e) => e.stopPropagation()}>
          <button
            type="button"
            className="rounded-lg p-2 transition hover:bg-stone-100 hover:text-stone-700"
            onClick={() => onEdit(account)}
            disabled={isUpdating}
          >
            <Pencil className="size-4" />
          </button>
          <button
            type="button"
            title="查看单账号日志时间线"
            className="rounded-lg p-2 transition hover:bg-stone-100 hover:text-stone-700"
            onClick={() => onTimeline(account)}
          >
            <History className="size-4" />
          </button>
          <button
            type="button"
            className="rounded-lg p-2 transition hover:bg-stone-100 hover:text-stone-700"
            onClick={() => onRefresh(account.access_token)}
            disabled={isRefreshing || refreshingTokens.has(account.access_token)}
          >
            <RefreshCw
              className={cn(
                "size-4",
                isRefreshing || refreshingTokens.has(account.access_token) ? "animate-spin" : "",
              )}
            />
          </button>
          <button
            type="button"
            className="rounded-lg p-2 transition hover:bg-rose-50 hover:text-rose-500"
            onClick={() => onDelete(account.access_token)}
            disabled={isDeleting}
          >
            <Trash2 className="size-4" />
          </button>
        </div>
      </div>
    </div>
  );
});