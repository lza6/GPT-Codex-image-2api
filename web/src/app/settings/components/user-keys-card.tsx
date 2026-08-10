"use client";

import { useEffect, useRef, useState } from "react";
import { Ban, CheckCircle2, Copy, KeyRound, LoaderCircle, Pencil, Plus, Trash2, XCircle } from "lucide-react";
import { toast } from "sonner";
import { toastError, toastSuccess } from "@/lib/toast-helper";
import { copyText } from "@/lib/clipboard";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  fetchApiKeys,
  createApiKey,
  updateApiKey,
  deleteApiKey,
  revokeApiKey,
  type ApiKey,
  type KeyQuota,
} from "@/lib/api";

function formatDateTime(value?: string | null) {
  if (!value) {
    return "—";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function formatDateValue(value?: string | null) {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toISOString().split("T")[0];
}

function getExpiryBadge(expiresAt: string | null): { variant: "success" | "warning" | "danger"; label: string } {
  if (!expiresAt) {
    return { variant: "success", label: "永不过期" };
  }
  const now = Date.now();
  const expiry = new Date(expiresAt).getTime();
  if (Number.isNaN(expiry)) {
    return { variant: "success", label: "永不过期" };
  }
  const diffDays = Math.ceil((expiry - now) / 86400000);
  if (diffDays <= 0) {
    return { variant: "danger", label: "已过期" };
  }
  if (diffDays <= 7) {
    return { variant: "warning", label: `距过期 ${diffDays} 天` };
  }
  return { variant: "success", label: `距过期 ${diffDays} 天` };
}

function QuotaProgressBar({ used, total, label }: { used: number; total: number | null; label: string }) {
  if (total === null || total === 0) {
    return null;
  }
  const pct = Math.min(Math.round((used / total) * 100), 100);
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="w-20 shrink-0 text-stone-500">{label}</span>
      <div className="flex h-2 flex-1 overflow-hidden rounded-full bg-stone-100">
        <div
          className={`h-full rounded-full transition-all ${
            pct >= 90 ? "bg-rose-500" : pct >= 70 ? "bg-amber-500" : "bg-emerald-500"
          }`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="w-24 shrink-0 text-right tabular-nums text-stone-500">
        {used} / {total}
      </span>
    </div>
  );
}

export function UserKeysCard() {
  const didLoadRef = useRef(false);
  const [items, setItems] = useState<ApiKey[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isDialogOpen, setIsDialogOpen] = useState(false);
  const [name, setName] = useState("");
  const [role, setRole] = useState<"admin" | "user">("user");
  const [expiresAt, setExpiresAt] = useState("");
  const [dailyRequests, setDailyRequests] = useState("");
  const [dailyImages, setDailyImages] = useState("");
  const [resetCycle, setResetCycle] = useState<KeyQuota["reset_cycle"]>("none");
  const [isCreating, setIsCreating] = useState(false);
  const [pendingIds, setPendingIds] = useState<Set<string>>(() => new Set());
  const [revealedKey, setRevealedKey] = useState("");
  const [deletingItem, setDeletingItem] = useState<ApiKey | null>(null);
  const [editingItem, setEditingItem] = useState<ApiKey | null>(null);
  const [editName, setEditName] = useState("");
  const [editExpiresAt, setEditExpiresAt] = useState("");
  const [editDailyRequests, setEditDailyRequests] = useState("");
  const [editDailyImages, setEditDailyImages] = useState("");
  const [editResetCycle, setEditResetCycle] = useState<KeyQuota["reset_cycle"]>("none");
  const [revokingItem, setRevokingItem] = useState<ApiKey | null>(null);

  const load = async () => {
    setIsLoading(true);
    try {
      const data = await fetchApiKeys();
      setItems(data.items);
    } catch (error) {
      toastError(error, "加载 API 密钥失败");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    if (didLoadRef.current) {
      return;
    }
    didLoadRef.current = true;
    void load();
  }, []);

  const handleCreate = async () => {
    setIsCreating(true);
    try {
      const quota: KeyQuota | undefined =
        dailyRequests || dailyImages
          ? {
              daily_requests: dailyRequests ? Number(dailyRequests) : null,
              daily_images: dailyImages ? Number(dailyImages) : null,
              monthly_requests: null,
              monthly_images: null,
              reset_cycle: resetCycle,
            }
          : undefined;
      const data = await createApiKey({
        name: name.trim() || undefined,
        role,
        expires_at: expiresAt || undefined,
        quota,
      });
      setItems(data.items);
      setRevealedKey(data.key);
      setName("");
      setRole("user");
      setExpiresAt("");
      setDailyRequests("");
      setDailyImages("");
      setResetCycle("none");
      setIsDialogOpen(false);
      toast.success("API 密钥已创建");
    } catch (error) {
      toastError(error, "创建 API 密钥失败");
    } finally {
      setIsCreating(false);
    }
  };

  const setItemPending = (id: string, isPending: boolean) => {
    setPendingIds((current) => {
      const next = new Set(current);
      if (isPending) {
        next.add(id);
      } else {
        next.delete(id);
      }
      return next;
    });
  };

  const handleToggle = async (item: ApiKey) => {
    setItemPending(item.id, true);
    try {
      const data = await updateApiKey(item.id, { enabled: !item.enabled });
      setItems(data.items);
      toast.success(item.enabled ? "API 密钥已禁用" : "API 密钥已启用");
    } catch (error) {
      toastError(error, "更新 API 密钥失败");
    } finally {
      setItemPending(item.id, false);
    }
  };

  const handleRevoke = async () => {
    if (!revokingItem) {
      return;
    }
    const item = revokingItem;
    setItemPending(item.id, true);
    try {
      const data = await revokeApiKey(item.id);
      setItems(data.items);
      setRevokingItem(null);
      toast.success("API 密钥已吊销");
    } catch (error) {
      toastError(error, "吊销 API 密钥失败");
    } finally {
      setItemPending(item.id, false);
    }
  };

  const handleDelete = async () => {
    if (!deletingItem) {
      return;
    }
    const item = deletingItem;
    setItemPending(item.id, true);
    try {
      const data = await deleteApiKey(item.id);
      setItems(data.items);
      setDeletingItem(null);
      toast.success("API 密钥已删除");
    } catch (error) {
      toastError(error, "删除 API 密钥失败");
    } finally {
      setItemPending(item.id, false);
    }
  };

  const openEditDialog = (item: ApiKey) => {
    setEditingItem(item);
    setEditName(item.name);
    setEditExpiresAt(formatDateValue(item.expires_at));
    setEditDailyRequests(item.quota?.daily_requests?.toString() ?? "");
    setEditDailyImages(item.quota?.daily_images?.toString() ?? "");
    setEditResetCycle(item.quota?.reset_cycle ?? "none");
  };

  const handleEdit = async () => {
    if (!editingItem) {
      return;
    }
    const item = editingItem;
    const trimmedName = editName.trim();
    const hasQuotaChanges =
      editDailyRequests !== (item.quota?.daily_requests?.toString() ?? "") ||
      editDailyImages !== (item.quota?.daily_images?.toString() ?? "") ||
      editResetCycle !== (item.quota?.reset_cycle ?? "none");
    const quota: KeyQuota | null =
      editDailyRequests || editDailyImages || hasQuotaChanges
        ? {
            daily_requests: editDailyRequests ? Number(editDailyRequests) : null,
            daily_images: editDailyImages ? Number(editDailyImages) : null,
            monthly_requests: null,
            monthly_images: null,
            reset_cycle: editResetCycle,
          }
        : null;
    setItemPending(item.id, true);
    try {
      const data = await updateApiKey(item.id, {
        ...(trimmedName !== item.name ? { name: trimmedName } : {}),
        ...(editExpiresAt !== formatDateValue(item.expires_at) ? { expires_at: editExpiresAt || null } : {}),
        ...(hasQuotaChanges ? { quota: editDailyRequests || editDailyImages ? quota : null } : {}),
      });
      setItems(data.items);
      setEditingItem(null);
      toast.success("API 密钥已更新");
    } catch (error) {
      toastError(error, "更新 API 密钥失败");
    } finally {
      setItemPending(item.id, false);
    }
  };

  const handleCopy = async (value: string) => {
    const ok = await copyText(value);
    if (ok) {
      toast.success("已复制到剪贴板");
    } else {
      toast.error("复制失败，请手动复制");
    }
  };

  return (
    <>
      <Card className="rounded-2xl border-white/80 bg-white/90 shadow-sm">
        <CardContent className="space-y-6 p-6">
          <div className="flex items-start justify-between gap-4">
            <div className="flex items-center gap-3">
              <div className="flex size-10 items-center justify-center rounded-xl bg-stone-100">
                <KeyRound className="size-5 text-stone-600" />
              </div>
              <div>
                <h2 className="text-lg font-semibold tracking-tight">API 密钥管理</h2>
                <p className="text-sm text-stone-500">管理员密钥只读展示；用户密钥支持配额、过期时间和权限控制。</p>
              </div>
            </div>
            <Button className="h-9 rounded-xl bg-stone-950 px-4 text-white hover:bg-stone-800" onClick={() => setIsDialogOpen(true)}>
              <Plus className="size-4" />
              创建密钥
            </Button>
          </div>

          {revealedKey ? (
            <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-4 text-sm text-emerald-900">
              <div className="font-medium">新密钥仅展示一次，请立即保存：</div>
              <div className="mt-3 flex flex-col gap-3 rounded-lg border border-emerald-200 bg-white/80 p-3 md:flex-row md:items-center md:justify-between">
                <code className="break-all font-mono text-[13px]">{revealedKey}</code>
                <Button
                  type="button"
                  variant="outline"
                  className="h-9 rounded-xl border-emerald-200 bg-white px-4 text-emerald-700"
                  onClick={() => void handleCopy(revealedKey)}
                >
                  <Copy className="size-4" />
                  复制
                </Button>
              </div>
            </div>
          ) : null}

          {isLoading ? (
            <div className="flex items-center justify-center py-10">
              <LoaderCircle className="size-5 animate-spin text-stone-400" />
            </div>
          ) : items.length === 0 ? (
            <div className="rounded-xl bg-stone-50 px-6 py-10 text-center text-sm text-stone-500">
              暂无 API 密钥。点击右上角按钮创建。
            </div>
          ) : (
            <div className="space-y-3">
              {items.map((item) => {
                const isPending = pendingIds.has(item.id);
                const isAdminKey = item.role === "admin";
                const expiryBadge = getExpiryBadge(item.expires_at);
                return (
                  <div key={item.id} className="flex flex-col gap-3 rounded-xl border border-stone-200 bg-white px-4 py-4 md:flex-row md:items-center md:justify-between">
                    <div className="min-w-0 space-y-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <div className="truncate text-sm font-medium text-stone-800">{item.name}</div>
                        <Badge variant={item.enabled ? "success" : "secondary"} className="rounded-md">
                          {item.enabled ? "已启用" : "已禁用"}
                        </Badge>
                        {isAdminKey ? (
                          <Badge variant="info" className="rounded-md">管理员</Badge>
                        ) : (
                          <Badge variant="violet" className="rounded-md">用户</Badge>
                        )}
                        <Badge variant={expiryBadge.variant} className="rounded-md">
                          {expiryBadge.label}
                        </Badge>
                      </div>
                      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-stone-500">
                        <span>创建时间 {formatDateTime(item.created_at)}</span>
                        <span>最近使用 {formatDateTime(item.last_used_at)}</span>
                        <span>调用次数 {item.usage_count}</span>
                      </div>
                      {item.quota && !isAdminKey ? (
                        <div className="space-y-1 pt-1">
                          <QuotaProgressBar
                            used={item.quota_used?.daily_requests ?? 0}
                            total={item.quota.daily_requests}
                            label="每日请求"
                          />
                          <QuotaProgressBar
                            used={item.quota_used?.daily_images ?? 0}
                            total={item.quota.daily_images}
                            label="每日图片"
                          />
                        </div>
                      ) : null}
                    </div>

                    {!isAdminKey ? (
                      <div className="flex items-center gap-2">
                        <Button
                          type="button"
                          variant="outline"
                          className="h-9 rounded-xl border-stone-200 bg-white px-3 text-stone-700"
                          onClick={() => void handleCopy(item.id)}
                          disabled={isPending}
                          title="复制密钥 ID"
                        >
                          <Copy className="size-4" />
                          复制
                        </Button>
                        <Button
                          type="button"
                          variant="outline"
                          className="h-9 rounded-xl border-stone-200 bg-white px-4 text-stone-700"
                          onClick={() => openEditDialog(item)}
                          disabled={isPending}
                        >
                          {isPending ? <LoaderCircle className="size-4 animate-spin" /> : <Pencil className="size-4" />}
                          编辑
                        </Button>
                        <Button
                          type="button"
                          variant="outline"
                          className="h-9 rounded-xl border-stone-200 bg-white px-4 text-stone-700"
                          onClick={() => void handleToggle(item)}
                          disabled={isPending}
                        >
                          {isPending ? (
                            <LoaderCircle className="size-4 animate-spin" />
                          ) : item.enabled ? (
                            <Ban className="size-4" />
                          ) : (
                            <CheckCircle2 className="size-4" />
                          )}
                          {item.enabled ? "禁用" : "启用"}
                        </Button>
                        <Button
                          type="button"
                          variant="outline"
                          className="h-9 rounded-xl border-amber-200 bg-white px-4 text-amber-700 hover:bg-amber-50"
                          onClick={() => setRevokingItem(item)}
                          disabled={isPending}
                          title="吊销密钥（禁用）"
                        >
                          {isPending ? <LoaderCircle className="size-4 animate-spin" /> : <XCircle className="size-4" />}
                          吊销
                        </Button>
                        <Button
                          type="button"
                          variant="outline"
                          className="h-9 rounded-xl border-rose-200 bg-white px-4 text-rose-600 hover:bg-rose-50 hover:text-rose-700"
                          onClick={() => setDeletingItem(item)}
                          disabled={isPending}
                        >
                          {isPending ? <LoaderCircle className="size-4 animate-spin" /> : <Trash2 className="size-4" />}
                          删除
                        </Button>
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>

      <Dialog open={isDialogOpen} onOpenChange={setIsDialogOpen}>
        <DialogContent className="rounded-2xl p-6">
          <DialogHeader className="gap-2">
            <DialogTitle>创建 API 密钥</DialogTitle>
            <DialogDescription className="text-sm leading-6">
              创建新的 API 密钥，可设置过期时间、角色和每日配额限制。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label className="text-sm font-medium text-stone-700">名称（可选）</Label>
              <Input
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="例如：设计同学 A、运营临时账号"
                className="h-11 rounded-xl border-stone-200 bg-white"
              />
            </div>
            <div className="space-y-2">
              <Label className="text-sm font-medium text-stone-700">角色</Label>
              <Select value={role} onValueChange={(v) => setRole(v as "admin" | "user")}>
                <SelectTrigger className="h-11 rounded-xl border-stone-200 bg-white">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="user">普通用户</SelectItem>
                  <SelectItem value="admin">管理员</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label className="text-sm font-medium text-stone-700">过期时间（可选）</Label>
              <Input
                type="date"
                value={expiresAt}
                onChange={(event) => setExpiresAt(event.target.value)}
                className="h-11 rounded-xl border-stone-200 bg-white"
              />
            </div>
            <div className="space-y-2">
              <Label className="text-sm font-medium text-stone-700">每日配额限制（可选）</Label>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-stone-500">每日请求数</label>
                  <Input
                    type="number"
                    min={0}
                    value={dailyRequests}
                    onChange={(event) => setDailyRequests(event.target.value)}
                    placeholder="不限"
                    className="h-11 rounded-xl border-stone-200 bg-white"
                  />
                </div>
                <div>
                  <label className="text-xs text-stone-500">每日图片数</label>
                  <Input
                    type="number"
                    min={0}
                    value={dailyImages}
                    onChange={(event) => setDailyImages(event.target.value)}
                    placeholder="不限"
                    className="h-11 rounded-xl border-stone-200 bg-white"
                  />
                </div>
              </div>
            </div>
            <div className="space-y-2">
              <Label className="text-sm font-medium text-stone-700">配额重置周期</Label>
              <Select value={resetCycle} onValueChange={(v) => setResetCycle(v as KeyQuota["reset_cycle"])}>
                <SelectTrigger className="h-11 rounded-xl border-stone-200 bg-white">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">无限制</SelectItem>
                  <SelectItem value="daily">每日重置</SelectItem>
                  <SelectItem value="monthly">每月重置</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="secondary"
              className="h-10 rounded-xl bg-stone-100 px-5 text-stone-700 hover:bg-stone-200"
              onClick={() => setIsDialogOpen(false)}
              disabled={isCreating}
            >
              取消
            </Button>
            <Button
              type="button"
              className="h-10 rounded-xl bg-stone-950 px-5 text-white hover:bg-stone-800"
              onClick={() => void handleCreate()}
              disabled={isCreating}
            >
              {isCreating ? <LoaderCircle className="size-4 animate-spin" /> : <Plus className="size-4" />}
              创建
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(deletingItem)} onOpenChange={(open) => (!open ? setDeletingItem(null) : null)}>
        <DialogContent className="rounded-2xl p-6">
          <DialogHeader className="gap-2">
            <DialogTitle>删除 API 密钥</DialogTitle>
            <DialogDescription className="text-sm leading-6">
              确认删除密钥「{deletingItem?.name}」吗？删除后该密钥将无法继续调用接口。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              type="button"
              variant="secondary"
              className="h-10 rounded-xl bg-stone-100 px-5 text-stone-700 hover:bg-stone-200"
              onClick={() => setDeletingItem(null)}
              disabled={deletingItem ? pendingIds.has(deletingItem.id) : false}
            >
              取消
            </Button>
            <Button
              type="button"
              className="h-10 rounded-xl bg-rose-600 px-5 text-white hover:bg-rose-700"
              onClick={() => void handleDelete()}
              disabled={deletingItem ? pendingIds.has(deletingItem.id) : false}
            >
              {deletingItem && pendingIds.has(deletingItem.id) ? <LoaderCircle className="size-4 animate-spin" /> : <Trash2 className="size-4" />}
              删除
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(revokingItem)} onOpenChange={(open) => (!open ? setRevokingItem(null) : null)}>
        <DialogContent className="rounded-2xl p-6">
          <DialogHeader className="gap-2">
            <DialogTitle>吊销 API 密钥</DialogTitle>
            <DialogDescription className="text-sm leading-6">
              确认吊销密钥「{revokingItem?.name}」吗？吊销后该密钥将立即禁用，无法继续调用接口。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              type="button"
              variant="secondary"
              className="h-10 rounded-xl bg-stone-100 px-5 text-stone-700 hover:bg-stone-200"
              onClick={() => setRevokingItem(null)}
              disabled={revokingItem ? pendingIds.has(revokingItem.id) : false}
            >
              取消
            </Button>
            <Button
              type="button"
              className="h-10 rounded-xl bg-amber-600 px-5 text-white hover:bg-amber-700"
              onClick={() => void handleRevoke()}
              disabled={revokingItem ? pendingIds.has(revokingItem.id) : false}
            >
              {revokingItem && pendingIds.has(revokingItem.id) ? <LoaderCircle className="size-4 animate-spin" /> : <XCircle className="size-4" />}
              吊销
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={Boolean(editingItem)}
        onOpenChange={(open) => {
          if (!open) {
            setEditingItem(null);
          }
        }}
      >
        <DialogContent className="rounded-2xl p-6">
          <DialogHeader className="gap-2">
            <DialogTitle>编辑 API 密钥</DialogTitle>
            <DialogDescription className="text-sm leading-6">
              修改名称、过期时间或配额限制。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label className="text-sm font-medium text-stone-700">名称</Label>
              <Input
                value={editName}
                onChange={(event) => setEditName(event.target.value)}
                placeholder="例如：设计同学 A、运营临时账号"
                className="h-11 rounded-xl border-stone-200 bg-white"
              />
            </div>
            <div className="space-y-2">
              <Label className="text-sm font-medium text-stone-700">过期时间（可选）</Label>
              <Input
                type="date"
                value={editExpiresAt}
                onChange={(event) => setEditExpiresAt(event.target.value)}
                className="h-11 rounded-xl border-stone-200 bg-white"
              />
            </div>
            <div className="space-y-2">
              <Label className="text-sm font-medium text-stone-700">每日配额限制（可选）</Label>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-stone-500">每日请求数</label>
                  <Input
                    type="number"
                    min={0}
                    value={editDailyRequests}
                    onChange={(event) => setEditDailyRequests(event.target.value)}
                    placeholder="不限"
                    className="h-11 rounded-xl border-stone-200 bg-white"
                  />
                </div>
                <div>
                  <label className="text-xs text-stone-500">每日图片数</label>
                  <Input
                    type="number"
                    min={0}
                    value={editDailyImages}
                    onChange={(event) => setEditDailyImages(event.target.value)}
                    placeholder="不限"
                    className="h-11 rounded-xl border-stone-200 bg-white"
                  />
                </div>
              </div>
            </div>
            <div className="space-y-2">
              <Label className="text-sm font-medium text-stone-700">配额重置周期</Label>
              <Select value={editResetCycle} onValueChange={(v) => setEditResetCycle(v as KeyQuota["reset_cycle"])}>
                <SelectTrigger className="h-11 rounded-xl border-stone-200 bg-white">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">无限制</SelectItem>
                  <SelectItem value="daily">每日重置</SelectItem>
                  <SelectItem value="monthly">每月重置</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="secondary"
              className="h-10 rounded-xl bg-stone-100 px-5 text-stone-700 hover:bg-stone-200"
              onClick={() => {
                setEditingItem(null);
              }}
              disabled={editingItem ? pendingIds.has(editingItem.id) : false}
            >
              取消
            </Button>
            <Button
              type="button"
              className="h-10 rounded-xl bg-stone-950 px-5 text-white hover:bg-stone-800"
              onClick={() => void handleEdit()}
              disabled={editingItem ? pendingIds.has(editingItem.id) : false}
            >
              {editingItem && pendingIds.has(editingItem.id) ? <LoaderCircle className="size-4 animate-spin" /> : <Pencil className="size-4" />}
              保存
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}