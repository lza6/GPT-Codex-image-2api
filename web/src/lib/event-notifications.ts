// ────────────────────────────────────────────────────────────────────────────
// 系统事件 → 通知中心 桥接（v2.40.0 G4）
// 数据源：GET /api/dashboard/events（读 data/events.jsonl，require_admin + Bearer）
// 职责：
//   1. 应用加载时拉取最近事件，映射为本地通知（type=alert/system）写入通知 store
//   2. 提供事件→人类可读文案 / severity / 跳转链接 的映射，供通知中心与 /notifications 复用
// 说明：这是"系统事件"这一通知来源，与既有 operation（操作结果）来源并存；
//       通知中心原有 localStorage 本地通知能力保持不变。
// ────────────────────────────────────────────────────────────────────────────

import type { DashboardEvent } from "@/lib/api";
import { fetchDashboardEvents } from "@/lib/api";
import { addNotification } from "@/store/notifications";

export type EventSeverity = "danger" | "success" | "info" | "neutral";

export type EventPresent = {
  title: string;
  message: string;
  severity: EventSeverity;
  href?: string;
};

// 事件类型 → 人类可读文案 / severity / 跳转目标
const EVENT_PRESENT: Record<string, (evt: DashboardEvent) => EventPresent> = {
  "account.invalid": (evt) => ({
    title: "账号失效",
    message: humanizeAccount(evt, "账号已被判定失效"),
    severity: "danger",
    href: "/accounts",
  }),
  "account.recovered": (evt) => ({
    title: "账号恢复",
    message: humanizeAccount(evt, "账号已恢复可用"),
    severity: "success",
    href: "/accounts",
  }),
  "account.quota_exhausted": (evt) => ({
    title: "配额耗尽",
    message: humanizeAccount(evt, "账号配额已耗尽"),
    severity: "danger",
    href: "/accounts",
  }),
  "account.quota_low": (evt) => ({
    title: "配额偏低",
    message: humanizeAccount(evt, "账号配额偏低"),
    severity: "neutral",
    href: "/accounts",
  }),
  "circuit.open": (evt) => ({
    title: "熔断开启",
    message: humanizeAccount(evt, "上游连续失败，已触发熔断"),
    severity: "danger",
    href: "/accounts",
  }),
  "circuit.half_open": (evt) => ({
    title: "熔断半开",
    message: humanizeAccount(evt, "熔断冷却结束，进入半开探测"),
    severity: "neutral",
    href: "/accounts",
  }),
  "circuit.closed": (evt) => ({
    title: "熔断恢复",
    message: humanizeAccount(evt, "熔断已恢复闭合"),
    severity: "success",
    href: "/accounts",
  }),
  "backup.failure": (evt) => ({
    title: "备份失败",
    message: humanizeBackup(evt, "备份任务执行失败"),
    severity: "danger",
    href: "/settings",
  }),
  "backup.checksum_mismatch": (evt) => ({
    title: "备份校验不通过",
    message: humanizeBackup(evt, "备份上传后校验和不匹配"),
    severity: "danger",
    href: "/settings",
  }),
  "provider.health_changed": (evt) => ({
    title: "提供商状态变更",
    message: humanizeProvider(evt),
    severity: "neutral",
  }),
  "session_pool.leak": (evt) => ({
    title: "连接池疑似泄漏",
    message: humanizeSessionPool(evt),
    severity: "danger",
  }),
};

// data 里的 token_suffix / account / email / error 等 → 人类可读片段
function humanizeAccount(evt: DashboardEvent, fallback: string): string {
  const data = evt.data ?? {};
  const who =
    typeof data.email === "string" && data.email
      ? data.email
      : typeof data.token_suffix === "string" && data.token_suffix
        ? `账号 …${data.token_suffix}`
        : "";
  const reason =
    typeof data.reason === "string" && data.reason
      ? `：${data.reason}`
      : typeof data.error === "string" && data.error
        ? `：${String(data.error).slice(0, 60)}`
        : "";
  return who ? `${who}${reason}` : fallback;
}

function humanizeBackup(evt: DashboardEvent, fallback: string): string {
  const data = evt.data ?? {};
  const err = typeof data.error === "string" && data.error ? String(data.error).slice(0, 60) : "";
  return err ? `${fallback}：${err}` : fallback;
}

function humanizeProvider(evt: DashboardEvent): string {
  const data = evt.data ?? {};
  const name =
    typeof data.provider === "string" && data.provider
      ? data.provider
      : typeof data.name === "string" && data.name
        ? data.name
        : "未知";
  return `提供商 ${name} 健康状态变化`;
}

function humanizeSessionPool(evt: DashboardEvent): string {
  const data = evt.data ?? {};
  const count =
    typeof data.leaked === "number"
      ? data.leaked
      : typeof data.count === "number"
        ? data.count
        : "";
  return count !== "" ? `检测到 ${count} 个疑似泄漏连接` : "检测到疑似泄漏连接";
}

/** 将后端事件转换为通知中心条目（幂等去重：按事件 id 记录已消费集合）。 */
export function eventToNotification(evt: DashboardEvent): { type: "alert" | "system"; title: string; message: string; metadata?: Record<string, unknown> } | null {
  const presenter = EVENT_PRESENT[evt.type];
  if (!presenter) return null;
  const present = presenter(evt);
  // circuit 开/半开/恢复 与 account 恢复 归为"系统通知"，其余告警
  const type: "alert" | "system" = present.severity === "danger" ? "alert" : "system";
  return {
    type,
    title: present.title,
    message: present.message,
    metadata: { severity: present.severity, href: present.href, eventType: evt.type },
  };
}

/** 事件 → 跳转链接（供通知中心点击跳转，未消费过才跳）。 */
export function eventHref(evt: DashboardEvent): string | undefined {
  const presenter = EVENT_PRESENT[evt.type];
  return presenter?.(evt).href;
}

const SEEN_KEY = "events-consumed-ids";
const SEEN_MAX = 500;

function seenIds(): Set<string> {
  if (typeof localStorage === "undefined") return new Set();
  try {
    const raw = localStorage.getItem(SEEN_KEY);
    return raw ? new Set(JSON.parse(raw) as string[]) : new Set();
  } catch {
    return new Set();
  }
}

function rememberSeen(ids: string[]) {
  if (typeof localStorage === "undefined") return;
  try {
    const next = [...new Set([...seenIds(), ...ids])].slice(-SEEN_MAX);
    localStorage.setItem(SEEN_KEY, JSON.stringify(next));
  } catch {
    /* localStorage 满则忽略 */
  }
}

/** 拉取最近事件并写入本地通知中心（去重：已消费过的事件不再重复通知）。 */
export async function syncEventsToNotifications(limit = 20): Promise<void> {
  try {
    const { events } = await fetchDashboardEvents(limit);
    if (!Array.isArray(events) || events.length === 0) return;
    const seen = seenIds();
    const fresh = events.filter((evt) => evt && typeof evt.id === "string" && !seen.has(evt.id));
    if (fresh.length === 0) return;
    rememberSeen(fresh.map((evt) => evt.id));
    for (const evt of fresh) {
      const item = eventToNotification(evt);
      if (item) addNotification({ ...item, id: evt.id });
    }
  } catch {
    // 后端不可达/未登录：静默失败（通知中心仍可用本地通知）
  }
}
