"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ComponentProps } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import {
  Ban,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  CircleOff,
  Copy,
  Download,
  History,
  Link2,
  LoaderCircle,
  LogIn,
  Pencil,
  RefreshCw,
  Search,
  Settings2,
  Tag,
  Trash2,
  UserRound,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { copyText } from "@/lib/clipboard";
import { toastError, toastSuccess, extractErrorMessage } from "@/lib/toast-helper";
import { setCache, getCache, hasCache } from "@/lib/offline-cache";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Skeleton, SkeletonCards, SkeletonTable } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/empty-state";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from "@/components/ui/sheet";
import {
  batchAccounts,
  deleteAccounts,
  evictStaleAccounts,
  exportAccounts,
  exportAccountsCSV,
  fetchAccounts,
  fetchAccountDetail,
  fetchAccountTags,
  fetchModels,
  fetchProviders,
  fetchProxies,
  fetchRefreshProgress,
  fetchReLoginProgress,
  fetchSystemLogs,
  probeKookeeyEgress,
  reLoginAccounts,
  recoverAbnormalAccounts,
  refreshAccounts,
  testProxy,
  updateAccount,
  type Account,
  type AccountColumnVisibility,
  type AccountDetail,
  type AccountRefreshResponse,
  type AccountStatus,
  type AccountTag,
  type KookeeyEgressResult,
  type Model,
  type ProviderInfo,
  type RefreshProgressResponse,
  type SystemLog,
} from "@/lib/api";
import { useAuthGuard } from "@/lib/use-auth-guard";
import { cn } from "@/lib/utils";
import { useKeyboard } from "@/hooks/use-keyboard";

// 批量操作增强：队列面板 / 结果弹窗 / 历史弹窗 + batch-queue store + 通知
import { BatchQueuePanel } from "@/components/batch-queue-panel";
import { BatchResultDialog } from "@/components/batch-result-dialog";
import { BatchHistoryDialog } from "@/components/batch-history-dialog";
import {
  cancel as cancelBatchItem,
  enqueue as enqueueBatchItem,
  getAbortController as getBatchAbortController,
  resume as resumeBatchItem,
  updateItemProgress as updateBatchItemProgress,
  updateItemResult as updateBatchItemResult,
  useBatchQueue,
  type BatchQueueItem,
} from "@/store/batch-queue";
import { addNotification, addOperationResult } from "@/store/notifications";

import { AccountImportDialog } from "./components/account-import-dialog";
import { AccountTableRow } from "./components/accounts-table-row";
import { TrashDialog } from "@/components/trash-dialog";

// 键盘快捷键：全局导航
const NAV_SHORTCUTS = [
  { key: "1", ctrl: true, handler: () => window.location.href = "/dashboard", description: "运维看板" },
  { key: "2", ctrl: true, handler: () => window.location.href = "/image", description: "生图" },
  { key: "3", ctrl: true, handler: () => window.location.href = "/accounts", description: "号池管理" },
  { key: "4", ctrl: true, handler: () => window.location.href = "/proxy-pool", description: "IP 池" },
  { key: "5", ctrl: true, handler: () => window.location.href = "/image-manager", description: "图片管理" },
  { key: "6", ctrl: true, handler: () => window.location.href = "/logs", description: "日志管理" },
  { key: "7", ctrl: true, handler: () => window.location.href = "/settings", description: "设置" },
  { key: "r", ctrl: true, handler: () => window.location.reload(), description: "刷新页面" },
];

const accountStatusOptions: { label: string; value: AccountStatus | "all" }[] = [
  { label: "全部状态", value: "all" },
  { label: "正常", value: "正常" },
  { label: "限流", value: "限流" },
  { label: "异常", value: "异常" },
  { label: "禁用", value: "禁用" },
];

const tierOptions: { label: string; value: string }[] = [
  { label: "全部档位", value: "all" },
  { label: "健康", value: "healthy" },
  { label: "温存", value: "warm" },
  { label: "风险", value: "risky" },
];

const sortOptions: { label: string; value: string }[] = [
  { label: "默认排序", value: "default" },
  { label: "调度分（高到低）", value: "score_desc" },
  { label: "调度分（低到高）", value: "score_asc" },
  { label: "配额（高到低）", value: "quota_desc" },
];

const statusMeta: Record<
  AccountStatus,
  {
    icon: typeof CheckCircle2;
    badge: ComponentProps<typeof Badge>["variant"];
  }
> = {
  正常: { icon: CheckCircle2, badge: "success" },
  限流: { icon: CircleAlert, badge: "warning" },
  异常: { icon: CircleOff, badge: "danger" },
  禁用: { icon: Ban, badge: "secondary" },
};

const metricCards = [
  { key: "total", label: "账户总数", color: "text-stone-900", icon: UserRound },
  { key: "active", label: "正常账户", color: "text-emerald-600", icon: CheckCircle2 },
  { key: "limited", label: "限流账户", color: "text-orange-500", icon: CircleAlert },
  { key: "abnormal", label: "异常账户", color: "text-rose-500", icon: CircleOff },
  { key: "disabled", label: "禁用账户", color: "text-stone-500", icon: Ban },
  { key: "quota", label: "剩余额度", color: "text-blue-500", icon: RefreshCw },
] as const;

// 可显隐列定义
const COLUMN_DEFINITIONS: { key: keyof AccountColumnVisibility; label: string }[] = [
  { key: "email", label: "邮箱" },
  { key: "type", label: "类型" },
  { key: "status", label: "状态" },
  { key: "provider", label: "提供商" },
  { key: "tier", label: "档位" },
  { key: "score", label: "调度分" },
  { key: "quota", label: "额度" },
  { key: "label", label: "标签" },
  { key: "proxy", label: "代理" },
  { key: "success", label: "成功数" },
  { key: "fail", label: "失败数" },
  { key: "image_inflight", label: "在途" },
  { key: "last_used_at", label: "最后使用" },
  { key: "created_at", label: "创建时间" },
  { key: "lifetime_risk", label: "寿命风险" },
  { key: "lifetime_eta_days", label: "剩余天数" },
  { key: "last_refresh_error", label: "异常原因" },
];

const COLUMN_VISIBILITY_KEY = "accounts-column-visibility";

// 选中项持久化 key
const SELECTED_IDS_KEY = "accounts-selected-ids";

// 列显隐默认值（全部可见）
const DEFAULT_COLUMN_VISIBILITY: AccountColumnVisibility = {
  email: true,
  type: true,
  status: true,
  provider: true,
  tier: true,
  score: true,
  quota: true,
  label: true,
  proxy: true,
  success: true,
  fail: true,
  image_inflight: true,
  last_used_at: true,
  created_at: true,
  lifetime_risk: true,
  lifetime_eta_days: true,
  last_refresh_error: true,
};

function loadColumnVisibility(): AccountColumnVisibility {
  if (typeof window === "undefined") return { ...DEFAULT_COLUMN_VISIBILITY };
  try {
    const stored = localStorage.getItem(COLUMN_VISIBILITY_KEY);
    if (stored) {
      return { ...DEFAULT_COLUMN_VISIBILITY, ...JSON.parse(stored) };
    }
  } catch {
    // ignore
  }
  return { ...DEFAULT_COLUMN_VISIBILITY };
}

function saveColumnVisibility(visibility: AccountColumnVisibility) {
  try {
    localStorage.setItem(COLUMN_VISIBILITY_KEY, JSON.stringify(visibility));
  } catch {
    // ignore
  }
}

function formatCompact(value: number) {
  if (value >= 1000) {
    return `${(value / 1000).toFixed(1)}k`;
  }
  return String(value);
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

function formatQuotaSummary(accounts: Account[]) {
  const availableAccounts = accounts.filter((account) => account.status === "正常");
  return formatCompact(availableAccounts.reduce((sum, account) => sum + Math.max(0, account.quota), 0));
}

function maskToken(token?: string) {
  if (!token) return "—";
  if (token.length <= 18) return token;
  return `${token.slice(0, 16)}...${token.slice(-8)}`;
}

async function downloadTokens(accounts: Account[]) {
  try {
    await exportAccounts(accounts.map((account) => account.access_token), "json");
  } catch (error) {
    toastError(error, "导出账号失败");
  }
}

function displayAccountType(account: Account) {
  return account.type || "Free";
}

function displayAccountSource(account: Account) {
  const source = String(account.source_type || "").trim().toLowerCase();
  if (!source) {
    return "web";
  }
  if (source === "web") {
    return "web";
  }
  return source;
}

function AccountsPageContent() {
  useKeyboard(NAV_SHORTCUTS);
  const didLoadRef = useRef(false);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [availableModels, setAvailableModels] = useState<Model[]>([]);
  // 选中项：从 localStorage 恢复（key: accounts-selected-ids）
  const [selectedIds, setSelectedIds] = useState<string[]>(() => {
    if (typeof window === "undefined") return [];
    try {
      const stored = localStorage.getItem(SELECTED_IDS_KEY);
      return stored ? (JSON.parse(stored) as string[]) : [];
    } catch {
      return [];
    }
  });
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState<AccountStatus | "all">("all");
  const [tierFilter, setTierFilter] = useState("all");
  const [sortBy, setSortBy] = useState("default");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState("10");
  // Phase B：provider 筛选器
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [providerFilter, setProviderFilter] = useState("all");
  // 标签筛选
  const [availableTags, setAvailableTags] = useState<AccountTag[]>([]);
  const [tagFilter, setTagFilter] = useState("all");
  const [editingAccount, setEditingAccount] = useState<Account | null>(null);
  const [editStatus, setEditStatus] = useState<AccountStatus>("正常");
  const [editProxy, setEditProxy] = useState("");
  // v2.9.0：账号编辑弹窗"从池选 IP"下拉数据
  const [poolProxies, setPoolProxies] = useState<{ url: string; host?: string; country?: string }[]>([]);
  const [isTestingProxy, setIsTestingProxy] = useState(false);
  // v2.9.0：账号 kookeey 粘性出口 IP 探测（编辑弹窗内"出口 IP"按钮）
  const [kookeeyEgress, setKookeeyEgress] = useState<KookeeyEgressResult | null>(null);
  const [isProbingEgress, setIsProbingEgress] = useState(false);
  const [timelineAccount, setTimelineAccount] = useState<Account | null>(null);
  const [timelineLogs, setTimelineLogs] = useState<SystemLog[]>([]);
  const [timelineLoading, setTimelineLoading] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingModels, setIsLoadingModels] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [refreshingTokens, setRefreshingTokens] = useState<Set<string>>(new Set());
  const [isDeleting, setIsDeleting] = useState(false);
  const [isUpdating, setIsUpdating] = useState(false);
  const [isRelogining, setIsRelogining] = useState(false);
  const [isEvicting, setIsEvicting] = useState(false);
  // 3.1.2：批量操作（按选中 ids 分发到 /api/accounts/batch）
  const [isBatchAction, setIsBatchAction] = useState(false);
  const [labelDialogOpen, setLabelDialogOpen] = useState(false);
  const [labelValue, setLabelValue] = useState("");
  // P1-3：ref 级防重入锁——React setState 异步生效，同一帧双击"一键刷新/删除"会双发请求，
  // 按钮 disabled 拦不住（下帧才生效）。用 ref 同步拦截。
  const busyRef = useRef(false);
  // 危险操作二次确认（第七轮 F1：删除/驱逐/清理异常与 image-manager/logs 确认模式对齐）
  const [confirmAction, setConfirmAction] = useState<{
    title: string;
    description: string;
    run: () => Promise<void>;
  } | null>(null);
  // 熔断状态：token 末 8 位 -> {state, recover_in_seconds}（仅含非 closed 账号）
  const [circuitBreakers, setCircuitBreakers] = useState<Record<string, { state: string; recover_in_seconds: number }>>({});
  const [progress, setProgress] = useState<{
    visible: boolean;
    current: number;
    total: number;
    message: string;
    email: string;
  }>({
    visible: false,
    current: 0,
    total: 0,
    message: "",
    email: "",
  });
  const progressRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [refreshSummary, setRefreshSummary] = useState<Record<string, number | string> | null>(null);

  // ── 批量操作增强 ──
  // batch-queue 订阅：每次 store 变更触发重渲染，queue() 返回最新活跃队列
  const { queue: batchQueueSnapshot } = useBatchQueue();
  const [batchResultItem, setBatchResultItem] = useState<BatchQueueItem | null>(null);
  const [batchHistoryOpen, setBatchHistoryOpen] = useState(false);

  // 列显隐
  const [columnVisibility, setColumnVisibility] = useState<AccountColumnVisibility>(loadColumnVisibility);

  // 选中计数
  const selectedCount = selectedIds.length;

  // 导出格式下拉
  const [exportPopoverOpen, setExportPopoverOpen] = useState(false);

  // 详情侧面板
  const [detailAccount, setDetailAccount] = useState<AccountDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailPanelOpen, setDetailPanelOpen] = useState(false);
  const [trashOpen, setTrashOpen] = useState(false);

  // 虚拟滚动
  const parentRef = useRef<HTMLDivElement>(null);
  const [useVirtualScroll, setUseVirtualScroll] = useState(true);

  // Shift+Click 范围选择
  const lastClickedIndexRef = useRef<number | null>(null);

  const loadAccounts = async (silent = false, providerParam?: string) => {
    if (!silent) {
      setIsLoading(true);
    }
    try {
      // 离线缓存：先尝试读取缓存
      const cached = getCache<Account[]>("accounts");
      if (cached && !navigator.onLine) {
        setAccounts(cached);
        return;
      }

      // Phase 4：providerParam 显式传入时以它为准（切换筛选器立即生效），否则用当前 state
      const activeProvider = providerParam !== undefined ? providerParam : providerFilter;
      const data = await fetchAccounts(activeProvider !== "all" ? activeProvider : undefined);
      setAccounts(data.items);
      // 写入缓存
      setCache("accounts", data.items);
      setSelectedIds((prev) => prev.filter((id) => data.items.some((item) => item.access_token === id)));
      // 熔断状态合并到账号列表响应
      if (data.breakers) {
        setCircuitBreakers(data.breakers);
      }
    } catch (error) {
      // 网络错误时尝试读缓存
      if (!navigator.onLine) {
        const cached = getCache<Account[]>("accounts");
        if (cached) {
          setAccounts(cached);
          toast.info("网络不可用，正在显示缓存数据");
          return;
        }
      }
      toastError(error, "加载账户失败");
    } finally {
      if (!silent) {
        setIsLoading(false);
      }
    }
  };

  const loadModels = async () => {
    setIsLoadingModels(true);
    try {
      const data = await fetchModels();
      setAvailableModels(Array.isArray(data.data) ? data.data : []);
    } catch (error) {
      toastError(error, "加载模型列表失败");
    } finally {
      setIsLoadingModels(false);
    }
  };

  // 选中项持久化到 localStorage（key: accounts-selected-ids）
  useEffect(() => {
    try {
      localStorage.setItem(SELECTED_IDS_KEY, JSON.stringify(selectedIds));
    } catch {
      // 存储失败忽略
    }
  }, [selectedIds]);

  // batch-queue 辅助：判断任务是否已被用户取消（用于轮询中止与静默返回）
  const isBatchAborted = useCallback((id: string) => getBatchAbortController(id)?.signal.aborted ?? false, []);

  // batch-queue 辅助：重试失败项（面板/结果弹窗的「重试」）
  const handleBatchResume = useCallback((item: BatchQueueItem) => {
    const failedTokens = item.tokens.filter((token) => item.results[token]?.success === false);
    if (failedTokens.length > 0) {
      resumeBatchItem(item.id, failedTokens);
    }
  }, []);

  useEffect(() => {
    if (didLoadRef.current) {
      return;
    }
    didLoadRef.current = true;
    void loadAccounts();
    void loadModels();

    // Phase B：加载已注册提供商列表供筛选器渲染
    void (async () => {
      try {
        const data = await fetchProviders();
        setProviders(data.providers);
      } catch {
        // 提供商列表加载失败不阻断
      }
    })();

    // 加载标签列表
    void (async () => {
      try {
        const data = await fetchAccountTags();
        setAvailableTags(data.tags ?? []);
      } catch {
        // 标签加载失败不阻断
      }
    })();

    // 熔断状态已合并到账号列表响应，不再单独轮询
    // 清理进度条定时器
    return () => {
      if (progressRef.current) clearInterval(progressRef.current);
    };
  }, []);

  const filteredAccounts = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    const filtered = accounts.filter((account) => {
      const searchMatched =
        normalizedQuery.length === 0 || (account.email ?? "").toLowerCase().includes(normalizedQuery);
      const typeMatched = typeFilter === "all" || displayAccountType(account) === typeFilter;
      const statusMatched = statusFilter === "all" || account.status === statusFilter;
      const tierMatched = tierFilter === "all" || account.tier === tierFilter;
      const tagMatched = tagFilter === "all" || account.label === tagFilter;
      return searchMatched && typeMatched && statusMatched && tierMatched && tagMatched;
    });
    // 排序：默认按状态可用性优先（正常→限流→异常→禁用），组内按 score 降序；其他模式按用户选择
    const sorted = [...filtered];
    const statusOrder: Record<string, number> = { "正常": 0, "限流": 1, "异常": 2, "禁用": 3 };
    if (sortBy === "score_desc") {
      sorted.sort((a, b) => (b.score ?? 0) - (a.score ?? 0));
    } else if (sortBy === "score_asc") {
      sorted.sort((a, b) => (a.score ?? 0) - (b.score ?? 0));
    } else if (sortBy === "quota_desc") {
      sorted.sort((a, b) => b.quota - a.quota);
    } else {
      // default：可用优先 —— 正常(quota>0) → 正常(quota=0) → 限流 → 异常 → 禁用，组内按 score 降序
      sorted.sort((a, b) => {
        const sa = statusOrder[a.status] ?? 9;
        const sb = statusOrder[b.status] ?? 9;
        if (sa !== sb) return sa - sb;
        if (sa === 0 && (a.quota > 0) !== (b.quota > 0)) return (b.quota > 0 ? 1 : 0) - (a.quota > 0 ? 1 : 0);
        return (b.score ?? 0) - (a.score ?? 0);
      });
    }
    return sorted;
  }, [accounts, query, statusFilter, typeFilter, tierFilter, tagFilter, sortBy]);

  const pageCount = Math.max(1, Math.ceil(filteredAccounts.length / Number(pageSize)));
  const safePage = Math.min(page, pageCount);
  const startIndex = (safePage - 1) * Number(pageSize);
  const currentRows = filteredAccounts.slice(startIndex, startIndex + Number(pageSize));
  const allCurrentSelected =
    currentRows.length > 0 && currentRows.every((row) => selectedIds.includes(row.access_token));

  // 虚拟滚动实例
  const virtualizer = useVirtualizer({
    count: useVirtualScroll ? filteredAccounts.length : 0,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 60,
    overscan: 10,
    enabled: useVirtualScroll && filteredAccounts.length > 0,
  });

  const summary = useMemo(() => {
    const total = accounts.length;
    const active = accounts.filter((item) => item.status === "正常").length;
    const limited = accounts.filter((item) => item.status === "限流").length;
    const abnormal = accounts.filter((item) => item.status === "异常").length;
    const disabled = accounts.filter((item) => item.status === "禁用").length;
    const quota = formatQuotaSummary(accounts);

    return { total, active, limited, abnormal, disabled, quota };
  }, [accounts]);

  const accountTypeOptions = useMemo(
    () => [
      { label: "全部类型", value: "all" },
      ...Array.from(new Set(accounts.map(displayAccountType))).map((type) => ({ label: type, value: type })),
    ],
    [accounts],
  );

  const selectedTokens = useMemo(() => {
    const selectedSet = new Set(selectedIds);
    return accounts.filter((item) => selectedSet.has(item.access_token)).map((item) => item.access_token);
  }, [accounts, selectedIds]);

  const abnormalTokens = useMemo(() => {
    return accounts.filter((item) => item.status === "异常").map((item) => item.access_token);
  }, [accounts]);

  const paginationItems = useMemo(() => {
    const items: (number | "...")[] = [];
    const start = Math.max(1, safePage - 1);
    const end = Math.min(pageCount, safePage + 1);

    if (start > 1) items.push(1);
    if (start > 2) items.push("...");
    for (let current = start; current <= end; current += 1) items.push(current);
    if (end < pageCount - 1) items.push("...");
    if (end < pageCount) items.push(pageCount);

    return items;
  }, [pageCount, safePage]);

  // Shift+Click 范围选择
  const handleToggleSelect = useCallback(
    (token: string, _checked: boolean, event: React.MouseEvent) => {
      if (event.shiftKey && lastClickedIndexRef.current !== null) {
        // Shift 范围选择
        const currentIndex = filteredAccounts.findIndex((a) => a.access_token === token);
        if (currentIndex === -1) return;
        const start = Math.min(lastClickedIndexRef.current, currentIndex);
        const end = Math.max(lastClickedIndexRef.current, currentIndex);
        const rangeTokens = filteredAccounts.slice(start, end + 1).map((a) => a.access_token);
        setSelectedIds((prev) => {
          const set = new Set(prev);
          for (const t of rangeTokens) set.add(t);
          return Array.from(set);
        });
      } else if (event.ctrlKey || event.metaKey) {
        // Ctrl 多选
        setSelectedIds((prev) =>
          prev.includes(token) ? prev.filter((t) => t !== token) : [...prev, token],
        );
      } else {
        // 常规点击
        setSelectedIds((prev) =>
          prev.includes(token) ? prev.filter((t) => t !== token) : [...prev, token],
        );
      }
      // 更新最后点击索引
      const idx = filteredAccounts.findIndex((a) => a.access_token === token);
      if (idx !== -1) lastClickedIndexRef.current = idx;
    },
    [filteredAccounts],
  );

  // 列显隐切换
  const toggleColumn = useCallback((key: keyof AccountColumnVisibility) => {
    setColumnVisibility((prev) => {
      const next = { ...prev, [key]: !prev[key] };
      saveColumnVisibility(next);
      return next;
    });
  }, []);

  // 打开详情侧面板
  const openDetailPanel = useCallback(async (account: Account) => {
    setDetailPanelOpen(true);
    setDetailLoading(true);
    setDetailAccount(null);
    try {
      const data = await fetchAccountDetail(account.access_token);
      setDetailAccount(data.item);
    } catch (error) {
      toastError(error, "加载账号详情失败");
      setDetailPanelOpen(false);
    } finally {
      setDetailLoading(false);
    }
  }, []);

  // 行点击：打开详情面板
  const handleRowClick = useCallback(
    (account: Account) => {
      void openDetailPanel(account);
    },
    [openDetailPanel],
  );

  const handleEvictStale = () => {
    setConfirmAction({
      title: "驱逐失效 Token？",
      description: "将从号池移除所有已失效（异常）账号的 token，此操作不可恢复。",
      run: async () => {
        setIsEvicting(true);
        try {
          const data = await evictStaleAccounts();
          if (data.stale === 0) {
            toast.info("当前没有失效（异常）账号");
          } else {
            toast.success(`已处理 ${data.stale} 个失效账号，驱逐 ${data.evicted} 个`);
          }
          await loadAccounts(true);
        } catch (error) {
          toastError(error, "驱逐失效账号失败");
        } finally {
          setIsEvicting(false);
        }
      },
    });
  };

  // 3.1.2：批量驱逐失效 token（仅选中账号中状态为「异常」的）
  const handleBatchEvictStale = () => {
    if (selectedTokens.length === 0) {
      toast.error("请先勾选账号");
      return;
    }
    setConfirmAction({
      title: `批量驱逐选中账号的失效 Token？`,
      description: `将对选中的 ${selectedTokens.length} 个账号执行失效驱逐（仅处理状态为「异常」的），不可恢复。`,
      run: async () => {
        setIsBatchAction(true);
        const tokens = selectedTokens;
        // 批量队列：入队驱逐任务（仅状态为「异常」的账号会被处理）
        const batchId = enqueueBatchItem({ action: "evict", label: "批量驱逐失效 token", tokens });
        try {
          const data = await batchAccounts("evict_stale", tokens);
          const processed = data.processed;
          const evicted = data.evicted ?? 0;
          // 批量队列：仅异常账号视为成功（接口无逐项结果），非异常视为跳过（不记录）
          const abnormalInSelection = tokens.filter(
            (t) => accounts.find((a) => a.access_token === t)?.status === "异常",
          );
          for (const t of abnormalInSelection) {
            updateBatchItemResult(batchId, t, true);
          }
          addOperationResult("批量驱逐完成", `已处理 ${processed} 个，驱逐 ${evicted} 个失效 token`, processed, 0);
          toast.success(`已处理 ${processed} 个，驱逐 ${evicted} 个失效 token`);
          await loadAccounts(true);
        } catch (error) {
          if (isBatchAborted(batchId)) return;
          for (const t of tokens) {
            updateBatchItemResult(batchId, t, false, extractErrorMessage(error));
          }
          addOperationResult("批量驱逐失败", extractErrorMessage(error), 0, tokens.length);
          toastError(error, "批量驱逐失败");
        } finally {
          setIsBatchAction(false);
        }
      },
    });
  };

  // 3.1.2：批量打标签（Dialog 输入标签 → label action）
  const handleBatchLabelSubmit = async () => {
    const label = labelValue.trim();
    if (!label) {
      toast.error("请输入标签");
      return;
    }
    if (selectedTokens.length === 0) {
      toast.error("请先勾选账号");
      return;
    }
    setIsBatchAction(true);
    const tokens = selectedTokens;
    // 批量队列：入队打标签任务
    const batchId = enqueueBatchItem({ action: "label", label: `标签「${label}」`, tokens });
    try {
      const data = await batchAccounts("label", tokens, label);
      const updated = data.updated ?? 0;
      const processed = data.processed;
      // 批量队列：接口无逐项结果，整体成功则全部标记成功
      for (const t of tokens) {
        updateBatchItemResult(batchId, t, true);
      }
      addOperationResult("批量打标签完成", `已为 ${updated}/${processed} 个账号设置标签「${label}」`, updated, processed - updated);
      toast.success(`已为 ${updated}/${processed} 个账号设置标签「${label}」`);
      setLabelDialogOpen(false);
      setLabelValue("");
      await loadAccounts(true);
    } catch (error) {
      if (isBatchAborted(batchId)) return;
      for (const t of tokens) {
        updateBatchItemResult(batchId, t, false, extractErrorMessage(error));
      }
      addOperationResult("批量打标签失败", extractErrorMessage(error), 0, tokens.length);
      toastError(error, "批量打标签失败");
    } finally {
      setIsBatchAction(false);
    }
  };

  // 3.1.2：批量导出选中（复用 export 接口三件套下载）
  const handleBatchExport = () => {
    if (selectedTokens.length === 0) {
      toast.error("请先勾选账号");
      return;
    }
    void downloadTokens(accounts.filter((item) => selectedTokens.includes(item.access_token)));
  };

  const handleExportSelected = (format: "csv" | "json") => {
    if (selectedTokens.length === 0) {
      toast.error("请先勾选账号");
      return;
    }
    setExportPopoverOpen(false);
    if (format === "csv") {
      void exportAccountsCSV({ format: "csv", ids: selectedTokens });
    } else {
      void downloadTokens(accounts.filter((item) => selectedTokens.includes(item.access_token)));
    }
  };

  const handleDeleteTokens = (tokens: string[]) => {
    if (tokens.length === 0) {
      toast.error("请先选择要删除的账户");
      return;
    }
    setConfirmAction({
      title: `删除 ${tokens.length} 个账户？`,
      description: "将从号池永久移除这些账号的 token，此操作不可恢复。",
      run: async () => {
        if (busyRef.current) return;
        busyRef.current = true;
        setIsDeleting(true);
        // 批量队列：入队删除任务
        const batchId = enqueueBatchItem({ action: "delete", label: `删除 ${tokens.length} 个账户`, tokens });
        try {
          const data = await deleteAccounts(tokens);
          setAccounts(data.items);
          setSelectedIds((prev) => prev.filter((id) => data.items.some((item) => item.access_token === id)));
          // 批量队列：被移除的 token 视为成功，其余视为失败
          const remainingTokens = new Set(data.items.map((item) => item.access_token));
          for (const t of tokens) {
            const deleted = !remainingTokens.has(t);
            updateBatchItemResult(batchId, t, deleted, deleted ? undefined : "账号未被删除");
          }
          const removed = data.removed ?? 0;
          addOperationResult("批量删除完成", `删除 ${removed} 个账户`, removed, tokens.length - removed);
          toast.success(`删除 ${removed} 个账户`);
        } catch (error) {
          if (isBatchAborted(batchId)) return;
          for (const t of tokens) {
            updateBatchItemResult(batchId, t, false, extractErrorMessage(error));
          }
          addOperationResult("批量删除失败", extractErrorMessage(error), 0, tokens.length);
          toastError(error, "删除账户失败");
        } finally {
          busyRef.current = false;
          setIsDeleting(false);
        }
      },
    });
  };

  const handleRefreshAccounts = async (accessTokens: string[]) => {
    if (accessTokens.length === 0) {
      toast.error("没有需要刷新的账户");
      return;
    }

    // 批量队列：入队本次刷新任务（单账号/多账号统一走队列）
    const batchId = enqueueBatchItem({ action: "refresh", label: "刷新账号信息", tokens: accessTokens });
    const isAborted = () => isBatchAborted(batchId);

    if (accessTokens.length === 1) {
      setRefreshingTokens((prev) => new Set([...prev, accessTokens[0]]));
      let okCount = 0;
      let failCount = 0;
      try {
        const { progress_id } = await refreshAccounts(accessTokens);
        // 单账号：轮询等待完成，同时收集结果
        await pollRefreshProgress(
          progress_id,
          (progress) => {
            if (progress.done && progress.result) {
              setAccounts(progress.result.items);
              setSelectedIds((prev) => prev.filter((id) => progress.result!.items.some((item) => item.access_token === id)));
            }
            updateBatchItemProgress(batchId, 100);
            const err = progress.result?.errors?.find((e) => e.access_token === accessTokens[0]);
            const success = !err;
            if (success) okCount += 1; else failCount += 1;
            updateBatchItemResult(batchId, accessTokens[0], success, err?.error ?? undefined);
          },
          isAborted,
        );
        if (!isAborted()) {
          addOperationResult(
            "批量刷新完成",
            okCount > 0 ? "刷新成功 1 个账户" : failCount > 0 ? "刷新失败" : "刷新完成",
            okCount,
            failCount,
          );
        }
      } catch (error) {
        if (isAborted()) return;
        updateBatchItemResult(batchId, accessTokens[0], false, extractErrorMessage(error));
        addOperationResult("批量刷新失败", extractErrorMessage(error), 0, 1);
        toastError(error, "刷新账户失败");
      } finally {
        setRefreshingTokens((prev) => {
          const next = new Set(prev);
          next.delete(accessTokens[0]);
          return next;
        });
      }
      return;
    }

    setIsRefreshing(true);
    if (busyRef.current) {
      setIsRefreshing(false);
      return;
    }
    busyRef.current = true;

    // 计算非选中账号的基数（统计卡片联动用）
    const selectedTokenSet = new Set(accessTokens);
    const baseAccountsList = accounts.filter((a) => !selectedTokenSet.has(a.access_token));
    const baseActive = baseAccountsList.filter((a) => a.status === "正常").length;
    const baseLimited = baseAccountsList.filter((a) => a.status === "限流").length;
    const baseAbnormal = baseAccountsList.filter((a) => a.status === "异常").length;
    const baseDisabled = baseAccountsList.filter((a) => a.status === "禁用").length;
    const baseNormalAccounts = baseAccountsList.filter((a) => a.status === "正常");
    const baseQuotaNum = baseNormalAccounts.reduce((s, a) => s + Math.max(0, a.quota), 0);

    // 显示进度条（只显示当前任务，不含分类统计）
    const total = accessTokens.length;
    setProgress({
      visible: true,
      current: 0,
      total,
      message: "正在刷新账号信息...",
      email: "",
    });

    try {
      const { progress_id } = await refreshAccounts(accessTokens);

      // 轮询进度到完成
      const data = await new Promise<AccountRefreshResponse>((resolve, reject) => {
        const pollTimer = setInterval(async () => {
          try {
            if (isAborted()) {
              clearInterval(pollTimer);
              reject(new DOMException("Aborted", "AbortError"));
              return;
            }
            const p = await fetchRefreshProgress(progress_id);
            if (p.done) {
              clearInterval(pollTimer);
              if (p.error) {
                reject(new Error(p.error));
                return;
              }
              if (!p.result) {
                reject(new Error("刷新结果为空"));
                return;
              }
              // 记录逐项结果（errors 中为失败项）
              const errorMap = new Map((p.result.errors ?? []).map((e) => [e.access_token, e.error]));
              for (const token of accessTokens) {
                const err = errorMap.get(token);
                updateBatchItemResult(batchId, token, !err, err ?? undefined);
              }
              // 更新最终进度显示
              setProgress((prev) => ({
                ...prev,
                current: prev.total,
                message: "刷新完成",
              }));
              // 清除联动统计
              setRefreshSummary(null);
              resolve(p.result);
            } else {
              // 实时更新进度
              setProgress((prev) => ({
                ...prev,
                current: p.processed,
              }));
              // batch 队列进度
              updateBatchItemProgress(batchId, p.total > 0 ? Math.round((p.processed / p.total) * 100) : 0);
              // 实时更新统计卡片：基数 + 已刷新的累加结果
              const runningActive = baseActive + ((p.status_counts?.["正常"]) ?? 0);
              const runningLimited = baseLimited + ((p.status_counts?.["限流"]) ?? 0);
              const runningAbnormal = baseAbnormal + ((p.status_counts?.["异常"]) ?? 0);
              const runningDisabled = baseDisabled + ((p.status_counts?.["禁用"]) ?? 0);
              setRefreshSummary({
                total: accounts.length,
                active: runningActive,
                limited: runningLimited,
                abnormal: runningAbnormal,
                disabled: runningDisabled,
                quota: formatCompact(baseQuotaNum + (p.total_quota ?? 0)),
              });
            }
          } catch (err) {
            clearInterval(pollTimer);
            reject(err);
          }
        }, 300);
      });

      // 刷新完成，更新数据
      setAccounts(data.items);
      setSelectedIds((prev) => prev.filter((id) => data.items.some((item) => item.access_token === id)));

      const relogined = data.relogined ?? 0;

      if (relogined > 0) {
        setProgress({
          visible: true,
          current: relogined,
          total: relogined,
          message: `已对 ${relogined} 个账号完成异常状态处理`,
          email: "",
        });
        setTimeout(() => setProgress({ visible: false, current: 0, total: 0, message: "", email: "" }), 1500);
      } else {
        setProgress({
          visible: true,
          current: total,
          total,
          message: "刷新完成",
          email: "",
        });
        setTimeout(() => setProgress({ visible: false, current: 0, total: 0, message: "", email: "" }), 800);
      }

      const refreshed = data.refreshed ?? 0;
      const failedCount = (data.errors ?? []).length;
      if (failedCount > 0) {
        const firstError = data.errors?.[0]?.error;
        toast.error(
          `刷新成功 ${refreshed} 个，失败 ${failedCount} 个${firstError ? `，首个错误：${firstError}` : ""}`,
        );
      } else {
        toast.success(`刷新成功 ${refreshed} 个账户${relogined > 0 ? `，已触发 ${relogined} 个账号重新登录` : ""}`);
      }
      addOperationResult(
        "批量刷新完成",
        `刷新成功 ${refreshed} 个账户${relogined > 0 ? `，已触发 ${relogined} 个账号重新登录` : ""}`,
        refreshed,
        failedCount,
      );
    } catch (error) {
      setProgress({ visible: false, current: 0, total: 0, message: "", email: "" });
      setRefreshSummary(null);
      if (isAborted()) return;
      for (const token of accessTokens) {
        updateBatchItemResult(batchId, token, false, extractErrorMessage(error));
      }
      addOperationResult("批量刷新失败", extractErrorMessage(error), 0, accessTokens.length);
      toastError(error, "刷新账户失败");
    } finally {
      busyRef.current = false;
      setIsRefreshing(false);
    }
  };

  const pollRefreshProgress = async (
    progressId: string,
    onUpdate: (p: RefreshProgressResponse) => void,
    isAborted?: () => boolean,
  ): Promise<void> => {
    return new Promise<void>((resolve, reject) => {
      const timer = setInterval(async () => {
        try {
          if (isAborted?.()) {
            clearInterval(timer);
            reject(new DOMException("Aborted", "AbortError"));
            return;
          }
          const p = await fetchRefreshProgress(progressId);
          if (p.done) {
            clearInterval(timer);
            if (p.error) {
              reject(new Error(p.error));
            } else {
              onUpdate(p);
              resolve();
            }
          }
        } catch (err) {
          clearInterval(timer);
          reject(err);
        }
      }, 500);
    });
  };

  const handleReLogin = async (accessTokens: string[]) => {
    if (accessTokens.length === 0) {
      toast.error("请先选择要恢复的账户");
      return;
    }

    // 只处理异常账号，过滤非异常账号
    const abnormalTokens = accessTokens.filter((token) => {
      const account = accounts.find((a) => a.access_token === token);
      return account?.status === "异常";
    });

    if (abnormalTokens.length === 0) {
      toast.error("选中账号中没有异常账号");
      return;
    }

    if (abnormalTokens.length < accessTokens.length) {
      toast.info(`已过滤 ${accessTokens.length - abnormalTokens.length} 个非异常账号`);
    }

    // v2.9.0：第一阶段——先调 recover（refresh_token 换 token 路径，覆盖纯 token 账号）
    setIsRelogining(true);
    let remainingAbnormalTokens = abnormalTokens;

    // 批量队列：入队本次恢复任务（recover + re-login 两阶段统一收集结果）
    const batchId = enqueueBatchItem({ action: "relogin", label: "恢复异常账号", tokens: abnormalTokens });
    const isAborted = () => isBatchAborted(batchId);
    let stageSuccess = 0;
    let stageFail = 0;

    try {
      toast.info(`正在尝试恢复 ${abnormalTokens.length} 个异常账号（refresh_token 路径）...`);
      const recoverResult = await recoverAbnormalAccounts(abnormalTokens);
      if (recoverResult.items) {
        setAccounts(recoverResult.items);
      }
      const recoveredCount = recoverResult.recovered ?? 0;
      if (recoveredCount > 0) {
        toast.success(`refresh_token 路径恢复成功 ${recoveredCount} 个账号`);
      }
      // 仍异常的账号走第二阶段密码重登
      remainingAbnormalTokens = recoverResult.items
        ? recoverResult.items
            .filter((a) => a.status === "异常" && abnormalTokens.includes(a.access_token))
            .map((a) => a.access_token)
        : abnormalTokens;
      // 批量队列：refresh_token 路径恢复成功的账号标记为成功
      const recoveredTokens = abnormalTokens.filter((t) => !remainingAbnormalTokens.includes(t));
      for (const t of recoveredTokens) {
        updateBatchItemResult(batchId, t, true);
        stageSuccess += 1;
      }
      if (remainingAbnormalTokens.length === 0) {
        addOperationResult("批量恢复完成", `refresh_token 路径恢复成功 ${recoveredCount} 个账号`, stageSuccess, stageFail);
        toast.success(`全部 ${abnormalTokens.length} 个异常账号已恢复`);
        setIsRelogining(false);
        await loadAccounts();
        return;
      }
      const hasPassword = remainingAbnormalTokens.filter((token) => {
        const a = accounts.find((x) => x.access_token === token);
        return a && (a as { password?: string }).password;
      });
      if (hasPassword.length === 0) {
        // 批量队列：无法恢复的账号标记失败
        for (const t of remainingAbnormalTokens) {
          updateBatchItemResult(batchId, t, false, "无邮箱密码，refresh_token 已失效");
          stageFail += 1;
        }
        addOperationResult("批量恢复完成", `仍有 ${remainingAbnormalTokens.length} 个异常账号无法恢复（无邮箱密码）`, stageSuccess, stageFail);
        toast.warning(`仍有 ${remainingAbnormalTokens.length} 个异常账号无法恢复（无邮箱密码，refresh_token 已失效）`);
        setIsRelogining(false);
        await loadAccounts();
        return;
      }
      toast.info(`仍异常 ${remainingAbnormalTokens.length} 个，对其中有密码的 ${hasPassword.length} 个尝试密码重登...`);
    } catch (recoverError) {
      console.warn("recover stage failed, fallback to re-login", recoverError);
    }
    setIsRelogining(false);

    // 计算非选中账号的基数（统计卡片联动用）—— 用 recover 后仍异常的 token 集
    const selectedTokenSet = new Set(remainingAbnormalTokens);
    const baseAccountsList = accounts.filter((a) => !selectedTokenSet.has(a.access_token));
    const baseActive = baseAccountsList.filter((a) => a.status === "正常").length;
    const baseLimited = baseAccountsList.filter((a) => a.status === "限流").length;
    const baseAbnormal = baseAccountsList.filter((a) => a.status === "异常").length;
    const baseDisabled = baseAccountsList.filter((a) => a.status === "禁用").length;

    // 显示进度条（真实进度）
    const total = remainingAbnormalTokens.length;
    setProgress({ visible: true, current: 0, total, message: "正在尝试恢复异常账号...", email: "" });

    try {
      const { progress_id } = await reLoginAccounts(remainingAbnormalTokens);

      // 轮询进度到完成
      await new Promise<void>((resolve, reject) => {
        const pollTimer = setInterval(async () => {
          try {
            if (isAborted()) {
              clearInterval(pollTimer);
              reject(new DOMException("Aborted", "AbortError"));
              return;
            }
            const p = await fetchReLoginProgress(progress_id);
            if (p.done) {
              clearInterval(pollTimer);
              if (p.error) {
                reject(new Error(p.error));
                return;
              }
              // 批量队列：记录逐项结果（status === "成功" 视为成功，未出现在结果中视为未处理）
              const resultMap = new Map((p.results ?? []).map((r) => [r.token, r]));
              for (const t of remainingAbnormalTokens) {
                const r = resultMap.get(t);
                const ok = r ? r.status === "成功" : false;
                updateBatchItemResult(batchId, t, ok, r?.error ?? (r ? undefined : "未处理"));
                if (ok) stageSuccess += 1; else stageFail += 1;
              }
              setProgress((prev) => ({ ...prev, current: prev.total, message: "恢复流程已完成" }));
              setRefreshSummary(null);
              resolve();
            } else {
              // 实时更新进度
              updateBatchItemProgress(batchId, p.total > 0 ? Math.round((p.processed / p.total) * 100) : 0);
              const results = p.results ?? [];
              const lastErrorResult = [...results].reverse().find((r) => r.error);
              const emailHint = lastErrorResult
                ? `失败: ${lastErrorResult.token} ${lastErrorResult.error ?? ""}`
                : `已处理 ${p.processed}/${p.total}`;
              setProgress((prev) => ({
                ...prev,
                current: p.processed,
                email: emailHint,
                message: "正在尝试恢复异常账号...",
              }));

              // 实时更新统计卡片：基数 + 已处理的恢复结果
              let runningActive = baseActive;
              let runningAbnormal = baseAbnormal;
              let runningDisabled = baseDisabled;
              for (const r of results) {
                if (r.status === "成功") {
                  runningActive += 1;
                  runningAbnormal -= 1;
                } else if (r.status === "禁用") {
                  runningDisabled += 1;
                  runningAbnormal -= 1;
                }
              }
              setRefreshSummary({
                total: accounts.length,
                active: runningActive,
                limited: baseLimited,
                abnormal: runningAbnormal,
                disabled: runningDisabled,
                quota: summary.quota,
              });
            }
          } catch (err) {
            clearInterval(pollTimer);
            reject(err);
          }
        }, 300);
      });

      // 等待后台线程完成，再拉取最新数据
      await new Promise<void>((resolve) => setTimeout(resolve, 500));
      try {
        const freshData = await fetchAccounts();
        setAccounts(freshData.items);
        setSelectedIds((prev) => prev.filter((id) => freshData.items.some((item) => item.access_token === id)));
      } catch { /* 静默失败 */ }

      setProgress({
        visible: true,
        current: total,
        total,
        message: "恢复完成",
        email: "",
      });
      setTimeout(() => setProgress({ visible: false, current: 0, total: 0, message: "", email: "" }), 800);

      toast.success(`恢复流程已全部完成`);
      addOperationResult("批量恢复完成", `恢复流程已全部完成（成功 ${stageSuccess}，失败 ${stageFail}）`, stageSuccess, stageFail);
    } catch (error) {
      setProgress({ visible: false, current: 0, total: 0, message: "", email: "" });
      setRefreshSummary(null);
      if (isAborted()) return;
      // 批量队列：剩余的（re-login 未处理）账号标记失败
      for (const t of remainingAbnormalTokens) {
        updateBatchItemResult(batchId, t, false, extractErrorMessage(error));
        stageFail += 1;
      }
      addOperationResult("批量恢复失败", extractErrorMessage(error), stageSuccess, stageFail);
      toastError(error, "重新登录失败");
    } finally {
      setIsRelogining(false);
    }
  };

  const openEditDialog = (account: Account) => {
    setEditingAccount(account);
    setEditStatus(account.status);
    setEditProxy(account.proxy ?? "");
    setKookeeyEgress(null);
    void (async () => {
      try {
        const data = await fetchProxies();
        setPoolProxies(data.proxies ?? []);
      } catch {
        // 拉取失败不阻断编辑
      }
    })();
  };

  // v2.9.0：探测该账号经 kookeey 粘性住宅代理的真实出口 IP
  const handleProbeKookeeyEgress = async () => {
    const email = (editingAccount?.email ?? "").trim();
    if (!email) {
      toast.error("该账号无邮箱，无法探测");
      return;
    }
    setIsProbingEgress(true);
    try {
      const result = await probeKookeeyEgress(email);
      setKookeeyEgress(result);
      if (result.ok && result.ip) {
        toast.success(`出口 IP: ${result.ip}`);
      } else if (result.enabled === false) {
        toast.error("kookeey 未启用");
      } else {
        toast.error(`探测失败：${result.error ?? "未知错误"}`);
      }
    } catch (error) {
      toastError(error, "探测出口 IP 失败");
    } finally {
      setIsProbingEgress(false);
    }
  };

  // 3.2.1：单账号洞察时间线——拉取该账号调用日志（复用 /api/logs?account_email= 过滤）
  const openTimeline = async (account: Account) => {
    const email = (account.email ?? account.access_token?.slice(-8) ?? "").trim();
    if (!email) {
      toast.error("该账号无邮箱/token 可过滤");
      setTimelineAccount(null);
      return;
    }
    setTimelineAccount(account);
    setTimelineLogs([]);
    setTimelineLoading(true);
    try {
      const data = await fetchSystemLogs({ type: "调用", account_email: email });
      setTimelineLogs(data.items);
    } catch (error) {
      toastError(error, "加载账号日志失败");
    } finally {
      setTimelineLoading(false);
    }
  };

  const handleTestAccountProxy = async () => {
    const candidate = editProxy.trim();
    if (!candidate) {
      toast.error("请先填写代理地址");
      return;
    }
    setIsTestingProxy(true);
    try {
      const data = await testProxy(candidate);
      data.result.ok
        ? toast.success(`代理可用（${data.result.latency_ms} ms，HTTP ${data.result.status}）`)
        : toast.error(`代理不可用：${data.result.error ?? "未知错误"}`);
    } catch (error) {
      toastError(error, "测试代理失败");
    } finally {
      setIsTestingProxy(false);
    }
  };

  const handleUpdateAccount = async () => {
    if (!editingAccount) {
      return;
    }

    setIsUpdating(true);
    try {
      const data = await updateAccount(editingAccount.access_token, {
        status: editStatus,
        proxy: editProxy.trim(),
      });
      setAccounts(data.items);
      setSelectedIds((prev) => prev.filter((id) => data.items.some((item) => item.access_token === id)));
      setEditingAccount(null);
      toast.success("账号信息已更新");
    } catch (error) {
      toastError(error, "更新账号失败");
    } finally {
      setIsUpdating(false);
    }
  };

  const toggleSelectAll = (checked: boolean) => {
    if (checked) {
      setSelectedIds((prev) => Array.from(new Set([...prev, ...currentRows.map((item) => item.access_token)])));
      return;
    }
    setSelectedIds((prev) => prev.filter((id) => !currentRows.some((row) => row.access_token === id)));
  };

  return (
    <>
      <section className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="space-y-1">
          <div className="text-xs font-semibold tracking-[0.18em] text-stone-500 uppercase">
            Account Pool
          </div>
          <h1 className="text-2xl font-semibold tracking-tight">号池管理</h1>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="outline"
            className="h-10 rounded-xl border-stone-200 bg-white/80 px-4 text-stone-700 hover:bg-white"
            onClick={() => void loadAccounts()}
            disabled={isLoading || isRefreshing || isDeleting}
          >
            <RefreshCw className={cn("size-4", isLoading ? "animate-spin" : "")} />
            刷新
          </Button>
          <Button
            variant="outline"
            className="h-10 rounded-xl border-stone-200 bg-white/80 px-4 text-stone-700 hover:bg-white"
            onClick={() => void handleRefreshAccounts(accounts.map((item) => item.access_token))}
            disabled={isLoading || isRefreshing || isDeleting || accounts.length === 0}
          >
            <RefreshCw className={cn("size-4", isRefreshing ? "animate-spin" : "")} />
            一键刷新所有账号信息和额度
          </Button>
          <AccountImportDialog
            disabled={isLoading || isRefreshing || isDeleting}
            onImported={(items) => {
              setAccounts(items);
              setSelectedIds([]);
              setPage(1);
            }}
          />
          <Button
            variant="outline"
            className="h-10 rounded-xl border-stone-200 bg-white/80 px-4 text-stone-700 hover:bg-white"
            onClick={() => downloadTokens(accounts)}
            disabled={accounts.length === 0}
          >
            <Download className="size-4" />
            导出全部 Token
          </Button>
          <Button
            variant="outline"
            className="h-10 rounded-xl border-stone-200 bg-white/80 px-4 text-stone-700 hover:bg-white"
            onClick={() => setBatchHistoryOpen(true)}
          >
            <History className="size-4" />
            操作历史
          </Button>
        </div>
      </section>

      {/* 批量操作队列面板（活跃任务 + 查看结果 / 重试 / 取消） */}
      <BatchQueuePanel
        queue={batchQueueSnapshot()}
        onCancel={(id) => {
          cancelBatchItem(id);
          addNotification({ type: "operation", title: "批量操作已取消", message: "任务已被手动取消" });
        }}
        onViewResult={setBatchResultItem}
        onResume={handleBatchResume}
        className="mb-4"
      />

      {/* 进度条 */}
      {progress.visible && (
        <div className="overflow-hidden rounded-2xl border border-stone-200 bg-white/90 shadow-sm">
          <div className="px-4 py-3">
            <div className="flex items-center justify-between text-sm">
              <span className="text-stone-600">
                {progress.message}
                {progress.email && <span className="ml-1 font-medium text-stone-700">{progress.email}</span>}
              </span>
              <span className="font-medium text-stone-700">
                {progress.current}/{progress.total}
              </span>
            </div>
            <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-stone-100">
              <div
                className="h-full rounded-full bg-gradient-to-r from-amber-400 to-orange-500 transition-all duration-300 ease-out"
                style={{ width: `${progress.total > 0 ? (progress.current / progress.total) * 100 : 0}%` }}
              />
            </div>
          </div>
        </div>
      )}

      <Dialog open={Boolean(editingAccount)} onOpenChange={(open) => (!open ? setEditingAccount(null) : null)}>
        <DialogContent showCloseButton={false} className="rounded-2xl p-6">
          <DialogHeader className="gap-2">
            <DialogTitle>编辑账户</DialogTitle>
            <DialogDescription className="text-sm leading-6">
              手动修改账号状态和专属代理。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <label className="text-sm font-medium text-stone-700">状态</label>
              <Select value={editStatus} onValueChange={(value) => setEditStatus(value as AccountStatus)}>
                <SelectTrigger className="h-11 rounded-xl border-stone-200 bg-white">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {accountStatusOptions
                    .filter((option) => option.value !== "all")
                    .map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.label}
                      </SelectItem>
                    ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium text-stone-700">账号代理</label>
              <div className="flex flex-col gap-2 sm:flex-row">
                <Input
                  value={editProxy}
                  onChange={(event) => setEditProxy(event.target.value)}
                  placeholder="留空走IP池轮询，例如 http://127.0.0.1:7890"
                  className="h-11 rounded-xl border-stone-200 bg-white"
                />
                {/* v2.9.0：从 IP 池选择代理绑定 */}
                <Select
                  value=""
                  onValueChange={(value) => {
                    if (value) setEditProxy(value);
                  }}
                >
                  <SelectTrigger className="h-11 rounded-xl border-stone-200 bg-white px-3 sm:w-40">
                    <SelectValue placeholder="从池选 IP" />
                  </SelectTrigger>
                  <SelectContent>
                    {poolProxies.map((p) => (
                      <SelectItem key={p.url} value={p.url}>
                        {p.host || p.url.slice(0, 30)}{p.country ? ` · ${p.country}` : ""}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Button
                  variant="outline"
                  className="h-11 rounded-xl border-stone-200 bg-white px-4 text-stone-700 sm:w-24"
                  onClick={() => void handleTestAccountProxy()}
                  disabled={isTestingProxy}
                >
                  {isTestingProxy ? <LoaderCircle className="size-4 animate-spin" /> : <Link2 className="size-4" />}
                  测试
                </Button>
              </div>
              {/* v2.9.0：该账号经 kookeey 粘性住宅代理的真实出口 IP 探测 */}
              <div className="flex items-center gap-2 rounded-xl border border-stone-200 bg-stone-50 px-3 py-2">
                <Button
                  variant="outline"
                  size="sm"
                  className="h-8 rounded-lg border-stone-200 bg-white px-3 text-stone-700"
                  onClick={() => void handleProbeKookeeyEgress()}
                  disabled={isProbingEgress}
                >
                  {isProbingEgress ? <LoaderCircle className="size-3.5 animate-spin" /> : <Search className="size-3.5" />}
                  出口 IP
                </Button>
                <div className="min-w-0 flex-1 text-xs text-stone-600">
                  {kookeeyEgress === null ? (
                    <span className="text-stone-400">探测该账号实际使用的住宅出口 IP（kookeey 粘性 session）</span>
                  ) : kookeeyEgress.ok && kookeeyEgress.ip ? (
                    <span>
                      出口 IP <span className="font-mono font-semibold text-stone-800">{kookeeyEgress.ip}</span>
                      {kookeeyEgress.session ? <span className="text-stone-400"> · session {kookeeyEgress.session}</span> : null}
                    </span>
                  ) : (
                    <span className="text-rose-600">
                      {kookeeyEgress.enabled === false ? "kookeey 未启用" : `探测失败：${kookeeyEgress.error ?? "未知"}`}
                    </span>
                  )}
                </div>
              </div>
            </div>
          </div>
          <DialogFooter className="pt-2">
            <Button
              variant="secondary"
              className="h-10 rounded-xl bg-stone-100 px-5 text-stone-700 hover:bg-stone-200"
              onClick={() => setEditingAccount(null)}
              disabled={isUpdating}
            >
              取消
            </Button>
            <Button
              className="h-10 rounded-xl bg-stone-950 px-5 text-white hover:bg-stone-800"
              onClick={() => void handleUpdateAccount()}
              disabled={isUpdating}
            >
              {isUpdating ? <LoaderCircle className="size-4 animate-spin" /> : null}
              保存修改
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 3.2.1：单账号洞察时间线抽屉 */}
      <Dialog open={Boolean(timelineAccount)} onOpenChange={(open) => (!open ? setTimelineAccount(null) : null)}>
        <DialogContent showCloseButton={false} className="rounded-2xl p-0">
          <DialogHeader className="gap-1 border-b border-stone-100 px-6 py-4">
            <DialogTitle>单账号时间线</DialogTitle>
            <DialogDescription className="truncate text-sm">
              {timelineAccount?.email ?? timelineAccount?.access_token?.slice(-8) ?? "-"}
            </DialogDescription>
          </DialogHeader>
          <div className="max-h-[55vh] overflow-y-auto px-6 py-4">
            {timelineLoading ? (
              <div className="flex items-center justify-center gap-2 py-10 text-sm text-stone-400">
                <LoaderCircle className="size-4 animate-spin" /> 加载中...
              </div>
            ) : timelineLogs.length === 0 ? (
              <p className="py-10 text-center text-sm text-stone-400">该账号暂无调用日志</p>
            ) : (
              <ul className="space-y-2">
                {timelineLogs.map((item) => (
                  <li
                    key={item.id}
                    className="flex items-center justify-between gap-3 rounded-lg border border-stone-100 px-3 py-2 text-sm"
                  >
                    <span className="min-w-0 flex-1 truncate text-stone-600">
                      <span className="font-medium text-stone-900">{item.summary ?? "-"}</span>
                      <span className="ml-2 text-xs text-stone-400">{item.time ?? ""}</span>
                    </span>
                    <Badge
                      variant={item.detail?.status === "failed" ? "danger" : "secondary"}
                      className="shrink-0 rounded-md"
                    >
                      {item.detail?.status === "failed" ? "失败" : "成功"}
                    </Badge>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <DialogFooter className="border-t border-stone-100 px-6 py-4">
            <Button
              variant="secondary"
              className="h-9 rounded-xl bg-stone-100 px-4 text-stone-700 hover:bg-stone-200"
              onClick={() => setTimelineAccount(null)}
            >
              关闭
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 3.1.2：批量打标签输入 Dialog */}
      <Dialog open={labelDialogOpen} onOpenChange={setLabelDialogOpen}>
        <DialogContent showCloseButton={false} className="rounded-2xl p-6">
          <DialogHeader className="gap-2">
            <DialogTitle>批量打标签</DialogTitle>
            <DialogDescription className="text-sm leading-6">
              为选中的 {selectedTokens.length} 个账号设置同一标签（显示在账号列表）。
            </DialogDescription>
          </DialogHeader>
          <Input
            value={labelValue}
            onChange={(event) => setLabelValue(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                void handleBatchLabelSubmit();
              }
            }}
            placeholder="例如：vip / 备用 / 团队A"
            className="h-11 rounded-xl border-stone-200 bg-white"
          />
          <DialogFooter className="pt-2">
            <Button
              variant="secondary"
              className="h-10 rounded-xl bg-stone-100 px-5 text-stone-700 hover:bg-stone-200"
              onClick={() => setLabelDialogOpen(false)}
              disabled={isBatchAction}
            >
              取消
            </Button>
            <Button
              className="h-10 rounded-xl bg-stone-950 px-5 text-white hover:bg-stone-800"
              onClick={() => void handleBatchLabelSubmit()}
              disabled={isBatchAction}
            >
              {isBatchAction ? <LoaderCircle className="size-4 animate-spin" /> : null}
              应用标签
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <section className="space-y-3">
        <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
          {metricCards.map((item) => {
            const Icon = item.icon;
            const value = (refreshSummary ?? summary)[item.key];
            return (
              <Card key={item.key} className="rounded-2xl border-white/80 bg-white/90 shadow-sm">
                <CardContent className="p-4">
                  <div className="mb-4 flex items-start justify-between">
                    <span className="text-xs font-medium text-stone-400">{item.label}</span>
                    <Icon className="size-4 text-stone-400" />
                  </div>
                  <div className={cn("text-[1.75rem] font-semibold tracking-tight", item.color)}>
                    <span className={typeof value === "number" ? "" : "text-[1.1rem]"}>
                      {typeof value === "number" ? formatCompact(value) : value}
                    </span>
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
        <Card className="rounded-2xl border-white/80 bg-white/90 shadow-sm">
          <CardContent className="p-4">
            <div className="mb-3 text-sm font-medium text-stone-700">
              系统可用模型
              <span className="ml-1 text-stone-400">({availableModels.length})</span>
            </div>
            <div className="flex flex-wrap gap-2">
              {availableModels.length > 0 ? (
                availableModels.map((model) => (
                  <button
                    key={model.id}
                    type="button"
                    className="inline-flex cursor-pointer items-center rounded-full border border-stone-200 bg-white px-2.5 py-1 text-xs font-medium text-stone-700 transition hover:border-stone-300 hover:bg-stone-50"
                    onClick={() => {
                      void copyText(model.id);
                      toast.success("模型名已复制");
                    }}
                    title={`点击复制 ${model.id}`}
                  >
                    <img
                      src="/openai.svg"
                      alt=""
                      aria-hidden="true"
                      className="mr-1.5 size-3.5 shrink-0"
                    />
                    {model.id}
                  </button>
                ))
              ) : isLoadingModels ? (
                <span className="text-sm text-stone-400">正在加载模型列表...</span>
              ) : (
                <span className="text-sm text-stone-400">当前暂无可用模型</span>
              )}
            </div>
          </CardContent>
        </Card>
      </section>

      <section className="space-y-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-center gap-3">
            <h2 className="text-lg font-semibold tracking-tight">账户列表</h2>
            <Badge variant="secondary" className="rounded-lg bg-stone-200 px-2 py-0.5 text-stone-700">
              {filteredAccounts.length}
            </Badge>
          </div>

          {/* v2.9.0：状态分组快捷 tab —— 一键切换"只看异常"等 */}
          <div className="flex flex-wrap items-center gap-2">
            {[
              { label: `全部 ${summary.total}`, value: "all" as const },
              { label: `正常 ${summary.active}`, value: "正常" as const },
              { label: `限流 ${summary.limited}`, value: "限流" as const },
              { label: `异常 ${summary.abnormal}`, value: "异常" as const },
              { label: `禁用 ${summary.disabled}`, value: "禁用" as const },
            ].map((tab) => {
              const active = statusFilter === tab.value;
              return (
                <button
                  key={tab.value}
                  type="button"
                  onClick={() => {
                    setStatusFilter(tab.value);
                    setPage(1);
                  }}
                  className={cn(
                    "inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition",
                    active
                      ? "bg-stone-900 text-white"
                      : "bg-stone-100 text-stone-600 hover:bg-stone-200",
                  )}
                >
                  {tab.label}
                </button>
              );
            })}
            {statusFilter === "异常" && abnormalTokens.length > 0 && (
              <button
                type="button"
                onClick={() => setSelectedIds(abnormalTokens)}
                className="ml-auto inline-flex items-center gap-1.5 rounded-lg bg-rose-50 px-3 py-1.5 text-xs font-medium text-rose-600 transition hover:bg-rose-100"
              >
                全选异常（{abnormalTokens.length}）
              </button>
            )}
          </div>

          <div className="flex flex-col gap-2 lg:flex-row lg:items-center">
            <div className="relative min-w-[260px]">
              <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-stone-400" />
              <Input
                value={query}
                onChange={(event) => {
                  setQuery(event.target.value);
                  setPage(1);
                }}
                placeholder="搜索邮箱"
                className="h-10 rounded-xl border-stone-200 bg-white/85 pl-10"
              />
            </div>
            <Select
              value={typeFilter}
              onValueChange={(value) => {
                setTypeFilter(value);
                setPage(1);
              }}
            >
              <SelectTrigger className="h-10 w-full rounded-xl border-stone-200 bg-white/85 lg:w-[150px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {accountTypeOptions.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {/* Phase B/4：provider 筛选器——切换后立即按所选 provider 重新拉取账号列表 */}
            <Select
              value={providerFilter}
              onValueChange={(value) => {
                setProviderFilter(value);
                setPage(1);
                void loadAccounts(false, value);
              }}
            >
              <SelectTrigger className="h-10 w-full rounded-xl border-stone-200 bg-white/85 lg:w-[130px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">全部提供商</SelectItem>
                {providers.map((p) => (
                  <SelectItem key={p.name} value={p.name} disabled={!p.enabled}>
                    <span className={cn(!p.enabled ? "text-stone-400" : "")}>
                      {p.display_name}{!p.enabled ? "（即将支持）" : ""}
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {/* 标签筛选 */}
            <Select
              value={tagFilter}
              onValueChange={(value) => {
                setTagFilter(value);
                setPage(1);
              }}
            >
              <SelectTrigger className="h-10 w-full rounded-xl border-stone-200 bg-white/85 lg:w-[130px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">全部标签</SelectItem>
                {availableTags.map((t) => (
                  <SelectItem key={t.name} value={t.name}>
                    <span className="flex items-center gap-1.5">
                      <span
                        className="inline-block size-2 rounded-full"
                        style={{ backgroundColor: t.color || "#888" }}
                      />
                      {t.name}
                    </span>
                  </SelectItem>
                ))}
                {availableTags.length === 0 && (
                  <SelectItem value="__no_tags__" disabled>
                    暂无标签
                  </SelectItem>
                )}
              </SelectContent>
            </Select>
            <Select
              value={statusFilter}
              onValueChange={(value) => {
                setStatusFilter(value as AccountStatus | "all");
                setPage(1);
              }}
            >
              <SelectTrigger className="h-10 w-full rounded-xl border-stone-200 bg-white/85 lg:w-[150px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {accountStatusOptions.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select
              value={tierFilter}
              onValueChange={(value) => {
                setTierFilter(value);
                setPage(1);
              }}
            >
              <SelectTrigger className="h-10 w-full rounded-xl border-stone-200 bg-white/85 lg:w-[130px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {tierOptions.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select
              value={sortBy}
              onValueChange={(value) => {
                setSortBy(value);
                setPage(1);
              }}
            >
              <SelectTrigger className="h-10 w-full rounded-xl border-stone-200 bg-white/85 lg:w-[150px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {sortOptions.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        {isLoading && accounts.length === 0 ? (
          <div className="space-y-4">
            <SkeletonCards count={6} className="h-24 rounded-2xl" />
            <Card className="rounded-2xl border-white/80 bg-white/90 shadow-sm">
              <CardContent className="p-4">
                <SkeletonTable rows={8} cols={8} />
              </CardContent>
            </Card>
          </div>
        ) : null}

        <Card
          className={cn(
            "overflow-hidden rounded-2xl border-white/80 bg-white/90 shadow-sm",
            isLoading && accounts.length === 0 ? "hidden" : "",
          )}
        >
          <CardContent className="space-y-0 p-0">
            <div className="flex flex-col gap-3 border-b border-stone-100 px-4 py-3 lg:flex-row lg:items-center lg:justify-between">
              <div className="flex flex-wrap items-center gap-2 text-sm text-stone-500">
                <Button
                  variant="ghost"
                  className="h-8 rounded-lg px-3 text-stone-500 hover:bg-stone-100"
                  onClick={() => void handleRefreshAccounts(selectedTokens)}
                  disabled={selectedTokens.length === 0 || isRefreshing}
                >
                  {isRefreshing ? <LoaderCircle className="size-4 animate-spin" /> : <RefreshCw className="size-4" />}
                  刷新选中账号信息和额度
                </Button>
                <Button
                  variant="ghost"
                  className="h-8 rounded-lg px-3 text-amber-600 hover:bg-amber-50 hover:text-amber-700"
                  onClick={() => void handleReLogin(selectedTokens)}
                  disabled={selectedTokens.length === 0 || isRelogining}
                  title="尝试密码登录恢复账号"
                >
                  {isRelogining ? <LoaderCircle className="size-4 animate-spin" /> : <LogIn className="size-4" />}
                  尝试恢复异常账号
                </Button>
                <Button
                  variant="ghost"
                  className="h-8 rounded-lg px-3 text-rose-500 hover:bg-rose-50 hover:text-rose-600"
                  onClick={() => void handleDeleteTokens(abnormalTokens)}
                  disabled={abnormalTokens.length === 0 || isDeleting}
                >
                  {isDeleting ? <LoaderCircle className="size-4 animate-spin" /> : <Trash2 className="size-4" />}
                  移除异常账号
                </Button>
                <Button
                  variant="ghost"
                  className="h-8 rounded-lg px-3 text-orange-500 hover:bg-orange-50 hover:text-orange-600"
                  onClick={() => void handleEvictStale()}
                  disabled={isEvicting}
                  title="对所有状态为「异常」的账号执行驱逐（移除或降级），并强制重建连接"
                >
                  {isEvicting ? <LoaderCircle className="size-4 animate-spin" /> : <CircleOff className="size-4" />}
                  驱逐失效token
                </Button>
                <Button
                  variant="ghost"
                  className="h-8 rounded-lg px-3 text-orange-500 hover:bg-orange-50 hover:text-orange-600"
                  onClick={() => void handleBatchEvictStale()}
                  disabled={selectedTokens.length === 0 || isBatchAction}
                  title="按选中账号批量驱逐失效 token（仅处理状态为「异常」的）"
                >
                  {isBatchAction ? <LoaderCircle className="size-4 animate-spin" /> : <Ban className="size-4" />}
                  批量驱逐失效
                </Button>
                <Button
                  variant="ghost"
                  className="h-8 rounded-lg px-3 text-violet-500 hover:bg-violet-50 hover:text-violet-600"
                  onClick={() => { setLabelValue(""); setLabelDialogOpen(true); }}
                  disabled={selectedTokens.length === 0 || isBatchAction}
                >
                  <Tag className="size-4" />
                  批量打标签
                </Button>
                <Button
                  variant="ghost"
                  className="h-8 rounded-lg px-3 text-stone-500 hover:bg-stone-100"
                  onClick={() => setTrashOpen(true)}
                  title="查看被自动剔除/手动删除的账号记录"
                >
                  <History className="size-4" />
                  回收站
                </Button>
                {/* 导出选中下拉（CSV/JSON） */}
                <Popover open={exportPopoverOpen} onOpenChange={setExportPopoverOpen}>
                  <PopoverTrigger asChild>
                    <Button
                      variant="ghost"
                      className="h-8 rounded-lg px-3 text-stone-500 hover:bg-stone-100"
                      disabled={selectedTokens.length === 0 || isBatchAction}
                    >
                      <Download className="size-4" />
                      导出选中
                    </Button>
                  </PopoverTrigger>
                  <PopoverContent className="w-36 p-1.5" align="start">
                    <button
                      type="button"
                      className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm text-stone-700 transition hover:bg-stone-100"
                      onClick={() => handleExportSelected("csv")}
                    >
                      <Download className="size-4 text-stone-400" />
                      导出 CSV
                    </button>
                    <button
                      type="button"
                      className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm text-stone-700 transition hover:bg-stone-100"
                      onClick={() => handleExportSelected("json")}
                    >
                      <Download className="size-4 text-stone-400" />
                      导出 JSON
                    </button>
                  </PopoverContent>
                </Popover>
                <Button
                  variant="ghost"
                  className="h-8 rounded-lg px-3 text-rose-500 hover:bg-rose-50 hover:text-rose-600"
                  onClick={() => void handleDeleteTokens(selectedTokens)}
                  disabled={selectedTokens.length === 0 || isDeleting}
                >
                  {isDeleting ? <LoaderCircle className="size-4 animate-spin" /> : <Trash2 className="size-4" />}
                  删除所选
                </Button>
                {selectedCount > 0 ? (
                  <span className="rounded-lg bg-stone-100 px-2.5 py-1 text-xs font-medium text-stone-600">
                    已选择 {selectedCount} 项
                  </span>
                ) : null}
                {/* 列显隐按钮 */}
                <Popover>
                  <PopoverTrigger asChild>
                    <Button
                      variant="ghost"
                      className="h-8 rounded-lg px-3 text-stone-500 hover:bg-stone-100"
                    >
                      <Settings2 className="size-4" />
                    </Button>
                  </PopoverTrigger>
                  <PopoverContent className="w-52 p-3" align="end">
                    <div className="mb-2 text-xs font-semibold text-stone-500 uppercase tracking-wide">
                      列显隐设置
                    </div>
                    <div className="max-h-64 space-y-1 overflow-y-auto">
                      {COLUMN_DEFINITIONS.map((col) => (
                        <label
                          key={col.key}
                          className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm text-stone-700 transition hover:bg-stone-100"
                        >
                          <Checkbox
                            checked={columnVisibility[col.key] !== false}
                            onCheckedChange={() => toggleColumn(col.key)}
                          />
                          {col.label}
                        </label>
                      ))}
                    </div>
                  </PopoverContent>
                </Popover>
              </div>
            </div>

            {/* 虚拟滚动表格区域 */}
            <div className="overflow-x-auto">
              {/* 移动端卡片列表（<768px） */}
              <div className="divide-y divide-stone-100 sm:hidden">
                {currentRows.map((account) => {
                  const StatusIcon = statusMeta[account.status]?.icon ?? CheckCircle2;
                  const badgeVariant = statusMeta[account.status]?.badge ?? "secondary";
                  return (
                    <div
                      key={account.access_token}
                      className="flex cursor-pointer items-center gap-3 px-4 py-3 transition hover:bg-stone-50"
                      onClick={() => handleRowClick(account)}
                    >
                      <Checkbox
                        checked={selectedIds.includes(account.access_token)}
                        onCheckedChange={(checked) => {
                          const event = { shiftKey: false, ctrlKey: false, metaKey: false } as React.MouseEvent;
                          handleToggleSelect(account.access_token, Boolean(checked), event);
                        }}
                      />
                      <div className="min-w-0 flex-1 space-y-1">
                        <div className="flex items-center gap-2">
                          <span className="truncate text-sm font-medium text-stone-900">
                            {account.email || account.access_token.slice(0, 16) + "..."}
                          </span>
                          <Badge variant={badgeVariant} className="shrink-0 rounded-md px-1.5 py-0 text-[10px]">
                            <StatusIcon className="mr-0.5 inline-block size-2.5" />
                            {account.status}
                          </Badge>
                        </div>
                        <div className="flex items-center gap-3 text-xs text-stone-400">
                          <span>{displayAccountType(account)}</span>
                          <span>额度 {formatQuota(account)}</span>
                          {account.tier && (
                            <span className={cn(
                              "rounded px-1 py-0.5 font-medium",
                              account.tier === "healthy" ? "text-emerald-600" : account.tier === "warm" ? "text-orange-500" : "text-rose-500",
                            )}>
                              {account.tier === "healthy" ? "健康" : account.tier === "warm" ? "温存" : "风险"}
                            </span>
                          )}
                          {account.label && (
                            <span className="rounded bg-stone-100 px-1.5 py-0.5 text-stone-500">
                              {account.label}
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                  );
                })}
                {!isLoading && currentRows.length === 0 && (
                  <div className="px-4 py-10 text-center text-sm text-stone-400">
                    没有匹配的账户
                  </div>
                )}
              </div>

              {/* 桌面端表格（>=768px） */}
              <div className="hidden sm:block">
                {/* 表头 */}
                <div className="flex min-w-[1000px] border-b border-stone-100 text-[11px] text-stone-400 uppercase tracking-[0.18em]">
                <div className="flex w-12 shrink-0 items-center px-4 py-3">
                  <Checkbox
                    checked={allCurrentSelected}
                    onCheckedChange={(checked) => toggleSelectAll(Boolean(checked))}
                  />
                </div>
                <div className="flex w-56 shrink-0 items-center px-4 py-3">token</div>
                {columnVisibility.type !== false && (
                  <div className="flex w-28 shrink-0 items-center px-4 py-3">类型</div>
                )}
                <div className="flex w-24 shrink-0 items-center px-4 py-3">来源</div>
                {columnVisibility.status !== false && (
                  <div className="flex w-24 shrink-0 items-center px-4 py-3">状态</div>
                )}
                {columnVisibility.lifetime_risk !== false && (
                  <div className="flex w-24 shrink-0 items-center px-4 py-3">寿命</div>
                )}
                <div className="flex w-24 shrink-0 items-center px-4 py-3">熔断</div>
                <div className="flex w-56 shrink-0 items-center px-4 py-3">账号信息</div>
                {columnVisibility.created_at !== false && (
                  <div className="flex w-32 shrink-0 items-center px-4 py-3">创建时间</div>
                )}
                {columnVisibility.quota !== false && (
                  <div className="flex w-24 shrink-0 items-center px-4 py-3">额度</div>
                )}
                <div className="flex w-40 shrink-0 items-center px-4 py-3">恢复时间</div>
                {columnVisibility.image_inflight !== false && (
                  <div className="flex w-18 shrink-0 items-center px-4 py-3">在途</div>
                )}
                {columnVisibility.success !== false && (
                  <div className="flex w-18 shrink-0 items-center px-4 py-3">成功</div>
                )}
                {columnVisibility.fail !== false && (
                  <div className="flex w-18 shrink-0 items-center px-4 py-3">失败</div>
                )}
                {columnVisibility.last_refresh_error !== false && (
                  <div className="flex w-48 shrink-0 items-center px-4 py-3">异常原因</div>
                )}
                <div className="flex w-24 shrink-0 items-center px-4 py-3">操作</div>
              </div>

              {/* 虚拟滚动容器 */}
              <div
                ref={parentRef}
                className="overflow-y-auto"
                style={{ maxHeight: useVirtualScroll ? "70vh" : undefined }}
              >
                {useVirtualScroll && filteredAccounts.length > 0 ? (
                  <div
                    className="relative min-w-[1000px]"
                    style={{ height: `${virtualizer.getTotalSize()}px` }}
                  >
                    {virtualizer.getVirtualItems().map((virtualItem) => {
                      const account = filteredAccounts[virtualItem.index];
                      if (!account) return null;
                      return (
                        <div
                          key={account.access_token}
                          className="absolute left-0 right-0"
                          style={{
                            height: `${virtualItem.size}px`,
                            transform: `translateY(${virtualItem.start}px)`,
                          }}
                        >
                          <AccountTableRow
                            account={account}
                            selected={selectedIds.includes(account.access_token)}
                            circuitBreakers={circuitBreakers}
                            refreshingTokens={refreshingTokens}
                            isRefreshing={isRefreshing}
                            isDeleting={isDeleting}
                            isUpdating={isUpdating}
                            onToggleSelect={handleToggleSelect}
                            onEdit={openEditDialog}
                            onTimeline={(acct) => void openTimeline(acct)}
                            onRefresh={(token) => void handleRefreshAccounts([token])}
                            onDelete={(token) => handleDeleteTokens([token])}
                            onClick={handleRowClick}
                            columnVisibility={columnVisibility}
                          />
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  /* 分页渲染（fallback） */
                  <>
                    <div className="min-w-[1000px]">
                      {currentRows.map((account) => (
                        <AccountTableRow
                          key={account.access_token}
                          account={account}
                          selected={selectedIds.includes(account.access_token)}
                          circuitBreakers={circuitBreakers}
                          refreshingTokens={refreshingTokens}
                          isRefreshing={isRefreshing}
                          isDeleting={isDeleting}
                          isUpdating={isUpdating}
                          onToggleSelect={handleToggleSelect}
                          onEdit={openEditDialog}
                          onTimeline={(acct) => void openTimeline(acct)}
                          onRefresh={(token) => void handleRefreshAccounts([token])}
                          onDelete={(token) => handleDeleteTokens([token])}
                          onClick={handleRowClick}
                          columnVisibility={columnVisibility}
                        />
                      ))}
                    </div>

                    {!isLoading && currentRows.length === 0 ? (
                      <>
                        {/* 桌面端空状态 */}
                        <div className="hidden sm:block">
                          <EmptyState
                            icon={<Search className="size-6" />}
                            title={
                              query
                                ? `没有匹配「${query}」的账户`
                                : statusFilter !== "all"
                                  ? `没有「${statusFilter}」状态的账户`
                                  : typeFilter !== "all"
                                    ? `没有「${typeFilter}」类型的账户`
                                    : tagFilter !== "all"
                                      ? `没有「${tagFilter}」标签的账户`
                                      : "没有匹配的账户"
                            }
                            description={
                              query
                                ? "尝试其他搜索关键字或清除筛选条件。"
                                : "调整筛选条件或搜索关键字后重试。"
                            }
                            action={
                              (query || statusFilter !== "all" || typeFilter !== "all" || tagFilter !== "all" || providerFilter !== "all" || tierFilter !== "all")
                                ? {
                                    label: "清除筛选",
                                    onClick: () => {
                                      setQuery("");
                                      setStatusFilter("all");
                                      setTypeFilter("all");
                                      setTagFilter("all");
                                      setProviderFilter("all");
                                      setTierFilter("all");
                                    },
                                  }
                                : undefined
                            }
                          />
                        </div>
                        {/* 移动端空状态 */}
                        <div className="sm:hidden">
                          <EmptyState
                            icon={<Search className="size-6" />}
                            title="没有匹配的账户"
                            description="调整筛选条件或搜索关键字后重试。"
                          />
                        </div>
                      </>
                    ) : null}
                  </>
                )}
              </div>
            </div>
          </div>

            {/* 分页控件 */}
            <div className="border-t border-stone-100 px-4 py-4">
              <div className="flex items-center justify-center gap-3 overflow-x-auto whitespace-nowrap">
                <div className="shrink-0 text-sm text-stone-500">
                  显示第 {filteredAccounts.length === 0 ? 0 : startIndex + 1} -{" "}
                  {Math.min(startIndex + Number(pageSize), filteredAccounts.length)} 条，共{" "}
                  {filteredAccounts.length} 条
                </div>

                <span className="shrink-0 text-sm leading-none text-stone-500">
                  {safePage} / {pageCount} 页
                </span>
                <Select
                  value={pageSize}
                  onValueChange={(value) => {
                    setPageSize(value);
                    setPage(1);
                  }}
                >
                  <SelectTrigger className="h-10 w-[108px] shrink-0 rounded-lg border-stone-200 bg-white text-sm leading-none">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="10">10 / 页</SelectItem>
                    <SelectItem value="20">20 / 页</SelectItem>
                    <SelectItem value="50">50 / 页</SelectItem>
                    <SelectItem value="100">100 / 页</SelectItem>
                  </SelectContent>
                </Select>
                <Button
                  variant="outline"
                  size="icon"
                  className="size-10 shrink-0 rounded-lg border-stone-200 bg-white"
                  disabled={safePage <= 1}
                  onClick={() => setPage((prev) => Math.max(1, prev - 1))}
                >
                  <ChevronLeft className="size-4" />
                </Button>
                {paginationItems.map((item, index) =>
                  item === "..." ? (
                    <span key={`ellipsis-${index}`} className="px-1 text-sm text-stone-400">
                      ...
                    </span>
                  ) : (
                    <Button
                      key={item}
                      variant={item === safePage ? "default" : "outline"}
                      className={cn(
                        "h-10 min-w-10 shrink-0 rounded-lg px-3",
                        item === safePage
                          ? "bg-stone-950 text-white hover:bg-stone-800"
                          : "border-stone-200 bg-white text-stone-700",
                      )}
                      onClick={() => setPage(item)}
                    >
                      {item}
                    </Button>
                  ),
                )}
                <Button
                  variant="outline"
                  size="icon"
                  className="size-10 shrink-0 rounded-lg border-stone-200 bg-white"
                  disabled={safePage >= pageCount}
                  onClick={() => setPage((prev) => Math.min(pageCount, prev + 1))}
                >
                  <ChevronRight className="size-4" />
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>
      </section>

      {/* 危险操作二次确认（删除/驱逐失效 token）——与 image-manager/logs 确认模式对齐 */}
      <Dialog open={confirmAction !== null} onOpenChange={(open) => { if (!open) setConfirmAction(null); }}>
        <DialogContent className="rounded-2xl">
          <DialogHeader>
            <DialogTitle>{confirmAction?.title}</DialogTitle>
            <DialogDescription>{confirmAction?.description}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              className="rounded-xl"
              onClick={() => setConfirmAction(null)}
              disabled={isDeleting || isEvicting}
            >
              取消
            </Button>
            <Button
              className="rounded-xl bg-rose-600 text-white hover:bg-rose-700"
              disabled={isDeleting || isEvicting}
              onClick={() => {
                const action = confirmAction;
                setConfirmAction(null);
                if (action) void action.run();
              }}
            >
              {(isDeleting || isEvicting) ? <LoaderCircle className="size-4 animate-spin" /> : null}
              确认执行
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 账号详情侧面板 */}
      <Sheet open={detailPanelOpen} onOpenChange={setDetailPanelOpen}>
        <SheetContent
          className="w-full rounded-l-2xl border-l border-stone-200 bg-white p-0 sm:max-w-md"
          showCloseButton={false}
        >
          <SheetHeader className="flex flex-row items-center justify-between border-b border-stone-100 px-6 py-4">
            <SheetTitle className="text-base font-semibold">账号详情</SheetTitle>
            <button
              type="button"
              className="rounded-lg p-1.5 text-stone-400 transition hover:bg-stone-100 hover:text-stone-700"
              onClick={() => setDetailPanelOpen(false)}
            >
              <X className="size-4" />
            </button>
          </SheetHeader>

          {detailLoading ? (
            <div className="flex items-center justify-center py-20">
              <LoaderCircle className="size-5 animate-spin text-stone-400" />
            </div>
          ) : detailAccount ? (
            <div className="overflow-y-auto px-6 py-4">
              <dl className="space-y-3 text-sm">
                <DetailRow label="邮箱" value={detailAccount.email ?? "—"} />
                <DetailRow
                  label="Token"
                  value={maskToken(detailAccount.access_token)}
                  copyable={detailAccount.access_token}
                />
                {detailAccount.refresh_token && (
                  <DetailRow
                    label="Refresh Token"
                    value={maskToken(detailAccount.refresh_token)}
                    copyable={detailAccount.refresh_token}
                  />
                )}
                {detailAccount.id_token && (
                  <DetailRow
                    label="ID Token"
                    value={maskToken(detailAccount.id_token)}
                    copyable={detailAccount.id_token}
                  />
                )}
                {detailAccount.password && (
                  <DetailRow label="密码" value={detailAccount.password} />
                )}
                <DetailRow label="类型" value={displayAccountType(detailAccount)} />
                <DetailRow label="来源" value={displayAccountSource(detailAccount)} />
                <DetailRow label="状态" value={detailAccount.status} />
                <DetailRow label="档位" value={detailAccount.tier ?? "—"} />
                <DetailRow label="调度分" value={String(detailAccount.score ?? "—")} />
                <DetailRow label="提供商" value={detailAccount.provider ?? "—"} />
                <DetailRow label="配额" value={formatQuota(detailAccount)} />
                <DetailRow label="创建时间" value={detailAccount.created_at ?? "—"} />
                <DetailRow label="代理" value={detailAccount.proxy ?? "—"} />
                <DetailRow label="标签" value={detailAccount.label ?? "—"} />
                <DetailRow
                  label="熔断状态"
                  value={
                    circuitBreakers[detailAccount.access_token.slice(-8)]
                      ? circuitBreakers[detailAccount.access_token.slice(-8)].state === "open"
                        ? "熔断中"
                        : "半开"
                      : "正常"
                  }
                />
                <DetailRow
                  label="寿命预测"
                  value={
                    detailAccount.lifetime_risk
                      ? `${({ low: "健康", medium: "关注", high: "偏高", critical: "濒危" } as Record<string, string>)[detailAccount.lifetime_risk] ?? "未知"}${detailAccount.lifetime_eta_days != null ? ` · ${detailAccount.lifetime_eta_days}d` : ""}`
                      : "—"
                  }
                />
                <DetailRow label="在途图片数" value={String(detailAccount.image_inflight ?? 0)} />
                <DetailRow label="成功次数" value={String(detailAccount.success)} />
                <DetailRow label="失败次数" value={String(detailAccount.fail)} />
                {detailAccount.tags && detailAccount.tags.length > 0 && (
                  <DetailRow
                    label="标签（扩展）"
                    value={detailAccount.tags.map((t) => t.name).join(", ")}
                  />
                )}
              </dl>

              {/* 底部操作按钮 */}
              <div className="mt-6 flex flex-wrap items-center gap-2 border-t border-stone-100 pt-4">
                <Button
                  variant="outline"
                  size="sm"
                  className="h-9 rounded-lg border-stone-200 text-stone-700"
                  onClick={() => openEditDialog(detailAccount)}
                >
                  <Pencil className="size-3.5" />
                  编辑
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  className="h-9 rounded-lg border-stone-200 text-stone-700"
                  onClick={() => void handleRefreshAccounts([detailAccount.access_token])}
                  disabled={isRefreshing}
                >
                  <RefreshCw className={cn("size-3.5", isRefreshing ? "animate-spin" : "")} />
                  刷新
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  className="h-9 rounded-lg border-stone-200 text-rose-600 hover:bg-rose-50"
                  onClick={() => {
                    setDetailPanelOpen(false);
                    handleDeleteTokens([detailAccount.access_token]);
                  }}
                  disabled={isDeleting}
                >
                  <Trash2 className="size-3.5" />
                  删除
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  className="h-9 rounded-lg border-stone-200 text-stone-700"
                  onClick={() => {
                    setDetailPanelOpen(false);
                    void openTimeline(detailAccount);
                  }}
                >
                  <History className="size-3.5" />
                  时间线
                </Button>
              </div>
            </div>
          ) : null}
        </SheetContent>
      </Sheet>

      {/* 回收站 */}
      <TrashDialog open={trashOpen} onOpenChange={setTrashOpen} />

      {/* 批量操作结果弹窗 */}
      <BatchResultDialog
        item={batchResultItem}
        onClose={() => setBatchResultItem(null)}
        onRetry={(failedTokens) => {
          if (batchResultItem) {
            resumeBatchItem(batchResultItem.id, failedTokens);
          }
          setBatchResultItem(null);
        }}
      />

      {/* 批量操作历史弹窗 */}
      <BatchHistoryDialog open={batchHistoryOpen} onOpenChange={setBatchHistoryOpen} />
    </>
  );
}

function DetailRow({ label, value, copyable }: { label: string; value: string; copyable?: string }) {
  return (
    <div className="flex items-start justify-between gap-2">
      <dt className="shrink-0 text-stone-500">{label}</dt>
      <dd className="flex items-center gap-1.5 text-right text-stone-900">
        <span className="break-all">{value}</span>
        {copyable && (
          <button
            type="button"
            className="shrink-0 rounded p-0.5 text-stone-400 transition hover:bg-stone-100 hover:text-stone-700"
            onClick={() => {
              void copyText(copyable);
              toast.success("已复制");
            }}
          >
            <Copy className="size-3.5" />
          </button>
        )}
      </dd>
    </div>
  );
}

export default function AccountsPage() {
  const { isCheckingAuth, session } = useAuthGuard(["admin"]);

  if (isCheckingAuth || !session || session.role !== "admin") {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <LoaderCircle className="size-5 animate-spin text-stone-400" />
      </div>
    );
  }

  return <AccountsPageContent />;
}