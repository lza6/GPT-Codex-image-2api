"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { ChevronLeft, ChevronRight, ImageIcon, LoaderCircle, RefreshCw, Search, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { toastError, toastSuccess } from "@/lib/toast-helper";

import { DateRangeFilter } from "@/components/date-range-filter";
import { ImageLightbox } from "@/components/image-lightbox";
import { ImageThumbnail, getImageThumbnailUrl } from "@/components/image-thumbnail";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { deleteSystemLogs, exportAuditCsv, fetchAuditLogs, fetchSystemLogs, type AuditLog, type SystemLog } from "@/lib/api";
import { useAuthGuard } from "@/lib/use-auth-guard";
import { useScrollMemory } from "@/hooks/use-scroll-memory";

const LogType = {
  Call: "call",
  Account: "account",
} as const;

const typeLabels: Record<string, string> = {
  [LogType.Call]: "调用日志",
  [LogType.Account]: "账号管理日志",
};

function getDetailText(item: SystemLog, key: string) {
  const value = item.detail?.[key];
  return typeof value === "string" || typeof value === "number" ? String(value) : "-";
}

function formatDuration(item: SystemLog) {
  const value = item.detail?.duration_ms;
  return typeof value === "number" ? `${(value / 1000).toFixed(2)} s` : "-";
}

function getUrls(item: SystemLog | null) {
  const urls = item?.detail?.urls;
  return Array.isArray(urls) ? urls.filter((url): url is string => typeof url === "string") : [];
}

function getStatus(item: SystemLog) {
  const status = item.detail?.status;
  if (status === "success") return "成功";
  if (status === "failed") return "失败";
  return "-";
}

function auditResultLabel(result: string) {
  if (result === "success") return { text: "成功", tone: "success" as const };
  if (result === "denied") return { text: "拒绝", tone: "danger" as const };
  if (result === "unauthorized") return { text: "未授权", tone: "danger" as const };
  return { text: result || "-", tone: "secondary" as const };
}

function AuditSection() {
  const [page, setPage] = useState(1);
  const [resultFilter, setResultFilter] = useState("all");
  const [actionFilter, setActionFilter] = useState("");
  const [operatorFilter, setOperatorFilter] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [auditItems, setAuditItems] = useState<AuditLog[]>([]);
  const [total, setTotal] = useState(0);
  const [auditPageLoading, setAuditPageLoading] = useState(false);
  const [hasLoaded, setHasLoaded] = useState(false);
  const pageSize = 10;

  const doLoad = async (p: number) => {
    setAuditPageLoading(true);
    try {
      const data = await fetchAuditLogs({
        days: 7,
        result: resultFilter !== "all" ? resultFilter : undefined,
        action: actionFilter || undefined,
        operator: operatorFilter || undefined,
        start_date: startDate || undefined,
        end_date: endDate || undefined,
        page: p,
        page_size: pageSize,
        limit: 200,
      });
      setAuditItems(data.items);
      setTotal(data.total ?? 0);
      setHasLoaded(true);
    } catch (error) {
      toastError(error, "加载审计日志失败");
    } finally {
      setAuditPageLoading(false);
    }
  };

  // Initial load on mount
  useEffect(() => {
    if (!hasLoaded) {
      void doLoad(1);
    }
  }, [hasLoaded]);

  const handleFilterChange = () => {
    setPage(1);
    void doLoad(1);
  };

  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const safePage = Math.min(page, pageCount);
  const currentRows = auditItems;

  // 统计卡片计算
  const stats = useMemo(() => {
    const today = new Date();
    const todayStr = today.toISOString().slice(0, 10);
    const todayItems = auditItems.filter((item) => item.ts?.startsWith(todayStr));
    const todayCount = todayItems.length;
    const failedCount = auditItems.filter((item) => item.result && item.result !== "success").length;
    const failRate = auditItems.length > 0 ? ((failedCount / auditItems.length) * 100).toFixed(1) : "0.0";
    const actionCounts: Record<string, number> = {};
    for (const item of auditItems) {
      const a = item.action || "-";
      actionCounts[a] = (actionCounts[a] || 0) + 1;
    }
    const topAction = Object.entries(actionCounts).sort((a, b) => b[1] - a[1])[0];
    return { todayCount, failRate, topAction: topAction ? `${topAction[0]} (${topAction[1]})` : "-" };
  }, [auditItems]);

  return (
    <Card className="overflow-hidden rounded-2xl border-white/80 bg-white/90 shadow-sm">
      <CardContent className="p-0">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-stone-100 px-5 py-4">
          <div className="flex items-center gap-3 text-sm text-stone-600">
            <span>共 {total} 条</span>
            <span className="text-xs text-stone-400">管理操作留痕（含失败），防篡改独立存储</span>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="ghost" className="h-8 rounded-lg px-3 text-stone-500" onClick={() => handleFilterChange()} disabled={auditPageLoading}>
              <RefreshCw className={`size-4 ${auditPageLoading ? "animate-spin" : ""}`} />
              刷新
            </Button>
            <Button variant="outline" className="h-8 rounded-lg border-stone-200 bg-white px-3 text-stone-700 text-xs" onClick={() => {
              void exportAuditCsv({
                days: 7,
                result: resultFilter !== "all" ? resultFilter : undefined,
                action: actionFilter || undefined,
                operator: operatorFilter || undefined,
                start_date: startDate || undefined,
                end_date: endDate || undefined,
              });
            }}>
              导出 CSV
            </Button>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-4 border-b border-stone-100 px-5 py-3 text-sm">
          <div className="flex items-center gap-2">
            <span className="text-stone-400">今日操作</span>
            <span className="font-semibold text-stone-700">{stats.todayCount}</span>
          </div>
          <div className="h-4 w-px bg-stone-200" />
          <div className="flex items-center gap-2">
            <span className="text-stone-400">失败率</span>
            <span className="font-semibold text-stone-700">{stats.failRate}%</span>
          </div>
          <div className="h-4 w-px bg-stone-200" />
          <div className="flex items-center gap-2">
            <span className="text-stone-400">TOP 操作</span>
            <span className="max-w-[200px] truncate font-medium text-stone-700">{stats.topAction}</span>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-3 border-b border-stone-100 px-5 py-3">
          <Select value={resultFilter} onValueChange={(v) => { setResultFilter(v); }}>
            <SelectTrigger className="h-8 w-[120px] rounded-lg border-stone-200 bg-white"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部结果</SelectItem>
              <SelectItem value="success">成功</SelectItem>
              <SelectItem value="denied">拒绝</SelectItem>
              <SelectItem value="unauthorized">未授权</SelectItem>
            </SelectContent>
          </Select>
          <Input
            value={actionFilter}
            onChange={(e) => { setActionFilter(e.target.value); }}
            placeholder="操作类型（如 /api/accounts）"
            className="h-8 w-[200px] rounded-lg border-stone-200 bg-white text-xs"
          />
          <Input
            value={operatorFilter}
            onChange={(e) => { setOperatorFilter(e.target.value); }}
            placeholder="操作者（末8位）"
            className="h-8 w-[160px] rounded-lg border-stone-200 bg-white text-xs"
          />
          <DateRangeFilter startDate={startDate} endDate={endDate} onChange={(s, e) => { setStartDate(s); setEndDate(e); }} />
          <Button
            variant="outline"
            className="h-8 rounded-lg border-stone-200 bg-white px-3 text-stone-700 text-xs"
            onClick={() => handleFilterChange()}
            disabled={auditPageLoading}
          >
            {auditPageLoading ? <LoaderCircle className="size-3 animate-spin" /> : <Search className="size-3" />}
            查询
          </Button>
        </div>
        <div className="overflow-x-auto">
          <Table className="min-w-[900px]">
            <TableHeader>
              <TableRow>
                <TableHead>时间</TableHead>
                <TableHead>方法</TableHead>
                <TableHead>操作</TableHead>
                <TableHead>结果</TableHead>
                <TableHead>操作者</TableHead>
                <TableHead>IP</TableHead>
                <TableHead>请求ID</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {currentRows.map((item) => {
                const result = auditResultLabel(item.result);
                return (
                  <TableRow key={item.id} className="text-stone-600">
                    <TableCell className="whitespace-nowrap">{item.ts}</TableCell>
                    <TableCell><Badge variant="secondary" className="rounded-md">{item.method || "-"}</Badge></TableCell>
                    <TableCell className="max-w-[300px] truncate font-medium text-stone-700">{item.action}</TableCell>
                    <TableCell>
                      <Badge variant={result.tone} className="rounded-md">{result.text}</Badge>
                    </TableCell>
                    <TableCell className="whitespace-nowrap font-mono text-xs">{item.operator || "-"}</TableCell>
                    <TableCell className="whitespace-nowrap">{item.ip || "-"}</TableCell>
                    <TableCell className="whitespace-nowrap font-mono text-xs">{item.request_id || "-"}</TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
        {total > pageSize ? (
          <div className="flex items-center justify-end gap-2 border-t border-stone-100 px-4 py-3 text-sm text-stone-500">
            <span>第 {safePage} / {pageCount} 页，共 {total} 条</span>
            <Button variant="outline" size="icon" className="size-9 rounded-lg border-stone-200 bg-white" disabled={safePage <= 1} onClick={() => { const np = safePage - 1; setPage(np); void doLoad(np); }}>
              <ChevronLeft className="size-4" />
            </Button>
            <Button variant="outline" size="icon" className="size-9 rounded-lg border-stone-200 bg-white" disabled={safePage >= pageCount} onClick={() => { const np = safePage + 1; setPage(np); void doLoad(np); }}>
              <ChevronRight className="size-4" />
            </Button>
          </div>
        ) : null}
        {!auditPageLoading && currentRows.length === 0 ? <div className="px-6 py-14 text-center text-sm text-stone-500">暂无审计记录</div> : null}
        {auditPageLoading ? <div className="flex items-center justify-center py-10"><LoaderCircle className="size-5 animate-spin text-stone-400" /></div> : null}
      </CardContent>
    </Card>
  );
}

// V-03：日志虚拟行（div 版，替代原 TableRow，配合 useVirtualizer 定位）
interface LogRowProps {
  item: SystemLog;
  isCallLog: boolean;
  selected: boolean;
  onToggleSelect: (checked: boolean) => void;
  onOpenDetail: (item: SystemLog) => void;
  onOpenImage: (item: SystemLog, index: number) => void;
  onDelete: (item: SystemLog) => void;
}

function LogRow({ item, isCallLog, selected, onToggleSelect, onOpenDetail, onOpenImage, onDelete }: LogRowProps) {
  const urls = getUrls(item);
  return (
    <div className="flex min-h-[52px] border-b border-stone-100 text-sm text-stone-600 transition-colors hover:bg-stone-50/70">
      <div className="flex w-12 shrink-0 items-center justify-center px-4">
        <Checkbox checked={selected} onCheckedChange={(c) => onToggleSelect(Boolean(c))} />
      </div>
      <div className="flex w-40 shrink-0 items-center px-4 text-xs whitespace-nowrap">{item.time}</div>
      <div className="flex w-24 shrink-0 items-center px-4">
        <Badge variant="secondary" className="rounded-md">{typeLabels[item.type] || item.type}</Badge>
      </div>
      {isCallLog ? <div className="flex w-28 shrink-0 items-center px-4">{getDetailText(item, "key_name")}</div> : null}
      {isCallLog ? <div className="flex w-24 shrink-0 items-center px-4">{formatDuration(item)}</div> : null}
      {isCallLog ? (
        <div className="flex w-20 shrink-0 items-center px-4">
          <Badge variant={item.detail?.status === "failed" ? "danger" : "success"} className="rounded-md">
            {getStatus(item)}
          </Badge>
        </div>
      ) : null}
      {isCallLog ? (
        <div className="flex w-36 shrink-0 items-center px-4">
          {urls.length ? (
            <div className="flex items-center gap-1.5">
              {urls.slice(0, 3).map((url, imageIndex) => (
                <button
                  key={`${url}-${imageIndex}`}
                  type="button"
                  className="relative size-9 overflow-hidden rounded-lg border border-stone-200 bg-stone-100"
                  onClick={() => onOpenImage(item, imageIndex)}
                  title="预览图片"
                >
                  <ImageThumbnail src={url} thumbnailSrc={getImageThumbnailUrl(url)} className="h-full w-full" />
                </button>
              ))}
              {urls.length > 3 ? <span className="text-xs text-stone-400">+{urls.length - 3}</span> : null}
            </div>
          ) : (
            <span className="inline-flex items-center gap-1 text-xs text-stone-400">
              <ImageIcon className="size-3.5" />
              -
            </span>
          )}
        </div>
      ) : null}
      <div className="flex min-w-0 flex-1 items-center px-4">
        <span className="truncate text-stone-500">{item.summary || "-"}</span>
      </div>
      <div className="flex w-40 shrink-0 items-center px-4">
        <div className="flex items-center gap-1">
          <Button variant="ghost" className="h-8 rounded-lg px-3 text-stone-600" onClick={() => onOpenDetail(item)}>
            查看详情
          </Button>
          <Button variant="ghost" className="h-8 rounded-lg px-3 text-rose-600 hover:bg-rose-50 hover:text-rose-700" onClick={() => onDelete(item)}>
            删除
          </Button>
        </div>
      </div>
    </div>
  );
}

function LogsContent() {
  const [items, setItems] = useState<SystemLog[]>([]);
  const [type, setType] = useState<string>(LogType.Call);
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  // v2.40.0 G4：全局搜索跳转预填账号邮箱（/logs?account_email=...），首次加载生效
  const [accountEmail, setAccountEmail] = useState(() => {
    if (typeof window === "undefined") return "";
    try {
      return new URLSearchParams(window.location.search).get("account_email") ?? "";
    } catch {
      return "";
    }
  });
  const [detailLog, setDetailLog] = useState<SystemLog | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [lightboxIndex, setLightboxIndex] = useState(0);
  const [lightboxOpen, setLightboxOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [isDeleting, setIsDeleting] = useState(false);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [deletingItems, setDeletingItems] = useState<SystemLog[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [levelFilter, setLevelFilter] = useState<string>("all");
  const [autoScroll, setAutoScroll] = useState(false);
  const [view, setView] = useState<"logs" | "audit">("logs");
  // V-03：日志列表虚拟滚动（滚动位置记忆 sessionStorage）
  const { ref: logsListRef, getSavedOffset: getLogsSavedOffset } = useScrollMemory<HTMLDivElement>("logs-list-scroll");
  const logsScrollRestoredRef = useRef(false);
  const detailUrls = getUrls(detailLog);
  const detailImages = detailUrls.map((url, index) => ({
    id: `${index}`,
    src: url.includes("chatgpt.com") || url.includes("oaidalle")
      ? `/api/images/proxy-download?url=${encodeURIComponent(url)}`
      : url,
  }));
  const isCallLog = type === LogType.Call;
  // 全文搜索 + 级别筛选
  const filteredItems = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    return items.filter((item) => {
      // 级别筛选（成功/失败）
      if (levelFilter !== "all") {
        const status = item.detail?.status;
        const isFailed = status === "failed";
        if (levelFilter === "failed" && !isFailed) return false;
        if (levelFilter === "success" && isFailed) return false;
      }
      // 全文搜索（summary + detail 内容，含 request_id）
      if (q) {
        const haystack = `${item.summary ?? ""} ${JSON.stringify(item.detail ?? {})}`.toLowerCase();
        if (!haystack.includes(q)) return false;
      }
      return true;
    });
  }, [items, searchQuery, levelFilter]);
  const selectedSet = useMemo(() => new Set(selectedIds), [selectedIds]);
  // V-03：虚拟列表一次展示全部筛选结果，「本页全选」即全选筛选结果
  const currentPageSelected = filteredItems.length > 0 && filteredItems.every((item) => selectedSet.has(item.id));
  const allSelected = items.length > 0 && items.every((item) => selectedSet.has(item.id));

  // V-03：日志列表虚拟化实例（父容器固定高度 + overflow scroll，行高自适应测量）
  const logsVirtualizer = useVirtualizer({
    count: filteredItems.length,
    getScrollElement: () => logsListRef.current,
    estimateSize: () => 52,
    overscan: 10,
    enabled: filteredItems.length > 0,
  });

  // 数据就绪后恢复上次滚动位置（sessionStorage 记忆，仅首次）
  useEffect(() => {
    const savedOffset = getLogsSavedOffset();
    if (!logsScrollRestoredRef.current && savedOffset > 0 && !isLoading && filteredItems.length > 0 && logsListRef.current) {
      logsScrollRestoredRef.current = true;
      logsVirtualizer.scrollToOffset(savedOffset);
    }
  }, [getLogsSavedOffset, isLoading, filteredItems.length, logsVirtualizer, logsListRef]);

  const loadLogs = async () => {
    setIsLoading(true);
    try {
      // 4.1：默认只读最近 7 天天文件（days=7 快），用户选日期范围时用 start_date/end_date 精确过滤
      const data = await fetchSystemLogs({
        type,
        start_date: startDate,
        end_date: endDate,
        account_email: accountEmail,
        days: 7,
      });
      setItems(data.items);
      setSelectedIds((current) => current.filter((id) => data.items.some((item) => item.id === id)));
    } catch (error) {
      toastError(error, "加载日志失败");
    } finally {
      setIsLoading(false);
    }
  };

  const clearFilters = () => {
    setStartDate("");
    setEndDate("");
    setAccountEmail("");
  };

  const openDetail = (item: SystemLog) => {
    setDetailLog(item);
    setDetailOpen(true);
  };

  const openLogImage = (item: SystemLog, index: number) => {
    setDetailLog(item);
    setLightboxIndex(index);
    setLightboxOpen(true);
  };

  const toggleIds = (ids: string[], checked: boolean) => {
    setSelectedIds((current) => checked ? Array.from(new Set([...current, ...ids])) : current.filter((id) => !ids.includes(id)));
  };

  const confirmDelete = async () => {
    const ids = deletingItems.map((item) => item.id);
    if (ids.length === 0) return;
    setIsDeleting(true);
    try {
      const data = await deleteSystemLogs(ids);
      toast.success(`已删除 ${data.removed} 条日志`);
      setDeletingItems([]);
      setSelectedIds((current) => current.filter((id) => !ids.includes(id)));
      if (detailLog && ids.includes(detailLog.id)) {
        setDetailOpen(false);
        setDetailLog(null);
      }
      await loadLogs();
    } catch (error) {
      toastError(error, "删除日志失败");
    } finally {
      setIsDeleting(false);
    }
  };

  useEffect(() => {
    void loadLogs();
  }, [type, startDate, endDate, accountEmail]);

  // 自动滚动：新日志加载后滚动到顶部
  useEffect(() => {
    if (autoScroll && !isLoading && filteredItems.length > 0) {
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
  }, [filteredItems, autoScroll, isLoading]);

  return (
    <section className="space-y-5">
      <Tabs value={view} onValueChange={(v) => { setView(v as "logs" | "audit"); }}>
        <TabsList className="h-10 rounded-xl border border-stone-200 bg-white">
          <TabsTrigger value="logs" className="rounded-lg px-4">业务日志</TabsTrigger>
          <TabsTrigger value="audit" className="rounded-lg px-4">审计日志</TabsTrigger>
        </TabsList>
      </Tabs>
      {view === "logs" ? (<>
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div className="space-y-1">
          <div className="text-xs font-semibold tracking-[0.18em] text-stone-500 uppercase">Logs</div>
          <h1 className="text-2xl font-semibold tracking-tight">日志管理</h1>
        </div>
        <div className="flex flex-wrap gap-2">
          <Select value={type} onValueChange={setType}>
            <SelectTrigger className="h-10 w-[150px] rounded-xl border-stone-200 bg-white"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value={LogType.Call}>调用日志</SelectItem>
              <SelectItem value={LogType.Account}>账号管理日志</SelectItem>
            </SelectContent>
          </Select>
          <Select value={levelFilter} onValueChange={(v) => { setLevelFilter(v); }}>
            <SelectTrigger className="h-10 w-[120px] rounded-xl border-stone-200 bg-white"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部级别</SelectItem>
              <SelectItem value="success">成功</SelectItem>
              <SelectItem value="failed">失败</SelectItem>
            </SelectContent>
          </Select>
          <div className="relative min-w-[220px]">
            <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-stone-400" />
            <Input
              value={searchQuery}
              onChange={(e) => { setSearchQuery(e.target.value); }}
              placeholder="搜索内容 / request_id"
              className="h-10 rounded-xl border-stone-200 bg-white pl-10"
            />
          </div>
          <div className="relative min-w-[200px]">
            <Input
              value={accountEmail}
              onChange={(e) => { setAccountEmail(e.target.value); }}
              placeholder="按账号邮箱 / 末8位过滤"
              className="h-10 rounded-xl border-stone-200 bg-white"
            />
          </div>
          <DateRangeFilter startDate={startDate} endDate={endDate} onChange={(start, end) => { setStartDate(start); setEndDate(end); }} />
          <label className="flex h-10 items-center gap-2 rounded-xl border border-stone-200 bg-white px-3 text-sm text-stone-600">
            <Checkbox checked={autoScroll} onCheckedChange={(c) => setAutoScroll(Boolean(c))} />
            自动滚动
          </label>
          <Button variant="outline" onClick={clearFilters} className="h-10 rounded-xl border-stone-200 bg-white px-4 text-stone-700">
            清除筛选条件
          </Button>
          <Button onClick={() => void loadLogs()} disabled={isLoading} className="h-10 rounded-xl bg-stone-950 px-4 text-white hover:bg-stone-800">
            {isLoading ? <LoaderCircle className="size-4 animate-spin" /> : <Search className="size-4" />}
            查询
          </Button>
        </div>
      </div>

      <Card className="overflow-hidden rounded-2xl border-white/80 bg-white/90 shadow-sm">
        <CardContent className="p-0">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-stone-100 px-5 py-4">
            <div className="flex flex-wrap items-center gap-3 text-sm text-stone-600">
              <span>共 {items.length} 条</span>
              <label className="flex items-center gap-2">
                <Checkbox checked={currentPageSelected} onCheckedChange={(checked) => toggleIds(filteredItems.map((item) => item.id), Boolean(checked))} />
                本页全选
              </label>
              <label className="flex items-center gap-2">
                <Checkbox checked={allSelected} onCheckedChange={(checked) => toggleIds(items.map((item) => item.id), Boolean(checked))} />
                全选结果
              </label>
              {selectedIds.length > 0 ? <span>已选 {selectedIds.length} 条</span> : null}
            </div>
            <div className="flex items-center gap-2">
              <Button variant="ghost" className="h-8 rounded-lg px-3 text-stone-500" onClick={() => void loadLogs()} disabled={isLoading}>
                <RefreshCw className={`size-4 ${isLoading ? "animate-spin" : ""}`} />
                刷新
              </Button>
              <button type="button" className="text-sm text-stone-500 hover:text-stone-900 disabled:text-stone-300" onClick={() => setSelectedIds([])} disabled={selectedIds.length === 0 || isDeleting}>
                取消选择
              </button>
              <Button variant="outline" className="h-8 rounded-lg border-rose-200 bg-white px-3 text-rose-600 hover:bg-rose-50" onClick={() => setDeletingItems(items.filter((item) => selectedSet.has(item.id)))} disabled={selectedIds.length === 0 || isDeleting}>
                <Trash2 className="size-4" />
                删除所选
              </Button>
            </div>
          </div>
          {/* V-03：日志列表虚拟化（父容器 h-[70vh] + overflow scroll，sticky 表头，行高自适应测量） */}
          <div ref={logsListRef} className="h-[70vh] min-w-0 overflow-auto">
            <div className="min-w-[900px]">
              <div className="sticky top-0 z-10 flex border-b border-stone-100 bg-white text-[11px] tracking-[0.18em] text-stone-400 uppercase">
                <div className="flex w-12 shrink-0 items-center px-4 py-3"></div>
                <div className="flex w-40 shrink-0 items-center px-4 py-3">时间</div>
                <div className="flex w-24 shrink-0 items-center px-4 py-3">类型</div>
                {isCallLog ? <div className="flex w-28 shrink-0 items-center px-4 py-3">令牌名称</div> : null}
                {isCallLog ? <div className="flex w-24 shrink-0 items-center px-4 py-3">调用耗时</div> : null}
                {isCallLog ? <div className="flex w-20 shrink-0 items-center px-4 py-3">状态</div> : null}
                {isCallLog ? <div className="flex w-36 shrink-0 items-center px-4 py-3">图片</div> : null}
                <div className="flex min-w-0 flex-1 items-center px-4 py-3">简述</div>
                <div className="flex w-40 shrink-0 items-center px-4 py-3">操作</div>
              </div>
              <div className="relative" style={{ height: `${logsVirtualizer.getTotalSize()}px` }}>
                {logsVirtualizer.getVirtualItems().map((virtualItem) => {
                  const item = filteredItems[virtualItem.index];
                  if (!item) return null;
                  return (
                    <div
                      key={virtualItem.key}
                      data-index={virtualItem.index}
                      ref={logsVirtualizer.measureElement}
                      className="absolute top-0 left-0 right-0"
                      style={{ transform: `translateY(${virtualItem.start}px)` }}
                    >
                      <LogRow
                        item={item}
                        isCallLog={isCallLog}
                        selected={selectedSet.has(item.id)}
                        onToggleSelect={(checked) => toggleIds([item.id], checked)}
                        onOpenDetail={openDetail}
                        onOpenImage={openLogImage}
                        onDelete={(log) => setDeletingItems([log])}
                      />
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
          <div className="flex items-center justify-end gap-2 border-t border-stone-100 px-4 py-3 text-sm text-stone-500">
            <span>共 {filteredItems.length} 条</span>
            <span className="text-stone-400">虚拟列表一次展示全部筛选结果</span>
          </div>
          {!isLoading && items.length === 0 ? <div className="px-6 py-14 text-center text-sm text-stone-500">没有找到日志</div> : null}
        </CardContent>
      </Card>
      <Dialog open={detailOpen} onOpenChange={setDetailOpen}>
        <DialogContent className="flex h-[min(88vh,860px)] w-[min(92vw,920px)] flex-col overflow-hidden rounded-2xl p-0">
          <DialogHeader className="shrink-0 border-b border-stone-100 px-6 py-5">
            <DialogTitle>日志详情</DialogTitle>
          </DialogHeader>
          <div className="flex-1 overflow-y-auto px-6 py-5">
            <div className="space-y-4">
              <div className="grid gap-3 rounded-xl border border-stone-200 bg-white p-4 text-sm text-stone-600 md:grid-cols-2">
                {Object.entries(detailLog?.detail || {})
                  .filter(([key, value]) => key !== "urls" && typeof value !== "object")
                  .map(([key, value]) => (
                    <div key={key} className="flex items-start justify-between gap-4">
                      <span className="text-stone-400">{key}</span>
                      <span className="text-right font-medium break-all text-stone-700">{String(value)}</span>
                    </div>
                  ))}
              </div>
              {detailUrls.length ? (
                <div className="grid gap-3 sm:grid-cols-2 md:grid-cols-3">
                  {detailUrls.map((url, index) => (
                    <button
                      key={url}
                      type="button"
                      className="aspect-square overflow-hidden rounded-xl border border-stone-200 bg-stone-100"
                      onClick={() => {
                        setLightboxIndex(index);
                        setLightboxOpen(true);
                      }}
                    >
                      <img src={url} alt="" className="h-full w-full object-cover" />
                    </button>
                  ))}
                </div>
              ) : null}
              <pre className="max-h-[72vh] overflow-auto rounded-xl border border-stone-200 bg-stone-50 p-4 text-xs leading-6 text-stone-700">
                {JSON.stringify(detailLog?.detail || {}, null, 2)}
              </pre>
            </div>
          </div>
        </DialogContent>
      </Dialog>
      <ImageLightbox
        images={detailImages}
        currentIndex={lightboxIndex}
        open={lightboxOpen}
        onOpenChange={setLightboxOpen}
        onIndexChange={setLightboxIndex}
      />
      <Dialog open={deletingItems.length > 0} onOpenChange={(open) => (!open ? setDeletingItems([]) : null)}>
        <DialogContent showCloseButton={false} className="rounded-2xl p-6">
          <DialogHeader className="gap-2">
            <DialogTitle>{deletingItems.length === 1 ? "删除日志" : "删除所选日志"}</DialogTitle>
            <DialogDescription className="text-sm leading-6">
              确认删除 {deletingItems.length} 条日志吗？删除后无法恢复。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" className="rounded-xl" onClick={() => setDeletingItems([])} disabled={isDeleting}>
              取消
            </Button>
            <Button className="rounded-xl bg-rose-600 text-white hover:bg-rose-700" onClick={() => void confirmDelete()} disabled={isDeleting || deletingItems.length === 0}>
              {isDeleting ? <LoaderCircle className="size-4 animate-spin" /> : null}
              确认删除
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      </>) : (
      <AuditSection />
      )}
    </section>
  );
}

export default function LogsPage() {
  const { isCheckingAuth, session } = useAuthGuard(["admin"]);
  if (isCheckingAuth || !session || session.role !== "admin") {
    return <div className="flex min-h-[40vh] items-center justify-center"><LoaderCircle className="size-5 animate-spin text-stone-400" /></div>;
  }
  return <LogsContent />;
}
