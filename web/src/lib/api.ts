import { httpRequest, request } from "@/lib/request";

export type AccountType = string;
export type AccountStatus = "正常" | "限流" | "异常" | "禁用";
export type ImageModel = string;
export type AuthRole = "admin" | "user";
export type ImageStorageMode = "local" | "webdav" | "both";

export type ImageStorageSettings = {
  enabled: boolean;
  mode: ImageStorageMode;
  webdav_url: string;
  webdav_username: string;
  webdav_password: string;
  webdav_root_path: string;
  public_base_url: string;
};

export type Account = {
  access_token: string;
  type: AccountType;
  source_type?: string | null;
  status: AccountStatus;
  quota: number;
  email?: string | null;
  user_id?: string | null;
  /** 账号创建时间（后端 list_accounts 实际返回，第七轮 F8 补声明，消灭 as any）。 */
  created_at?: string | null;
  limits_progress?: Array<{
    feature_name?: string;
    remaining?: number;
    reset_after?: string;
  }>;
  default_model_slug?: string | null;
  restore_at?: string | null;
  success: number;
  fail: number;
  /** 当前图片在途数(正在生成、尚未结束的图片数)。号池空闲时持续 > 0 表示并发槽位泄漏。 */
  image_inflight?: number;
  last_used_at?: string | null;
  proxy?: string | null;
  /** 3.1.2：账号标签（批量打标签写入）。 */
  label?: string;
  /** 健康档位（healthy/warm/risky）。 */
  tier?: SchedulerTier;
  /** 调度分。 */
  score?: number;
  /** 5.1：账号寿命预测风险档位（low/medium/high/critical）。 */
  lifetime_risk?: "low" | "medium" | "high" | "critical";
  /** 5.1：预估剩余可用天数。 */
  lifetime_eta_days?: number | null;
  lifetime_score?: number;
  /** v2.9.0：异常账号根因可视化 —— 最近刷新错误描述。 */
  last_refresh_error?: string | null;
  /** v2.9.0：最近刷新错误时间。 */
  last_refresh_error_at?: string | null;
  /** v2.9.0：最近 token 刷新错误描述。 */
  last_token_refresh_error?: string | null;
  /** v2.9.0：最近 token 刷新错误时间。 */
  last_token_refresh_error_at?: string | null;
  /** v2.9.0：累计失效次数。 */
  invalid_count?: number;
  /** v2.9.0：最近失效时间。 */
  last_invalid_at?: string | null;
  /** Phase B：账号归属提供商（"chatgpt" / "grok" 等）。 */
  provider?: string;
};

export type AccountImportPayload = {
  // 纯账号密码导入时无 access_token，后端会按 email+password 自动登录抓 token 入库。
  access_token?: string;
  accessToken?: string;
  email?: string;
  password?: string;
  // 4 段卡密格式（邮箱----密码----client_id----refresh_token）时带，可自动过 OTP
  mail_credential?: {
    client_id: string;
    refresh_token: string;
  };
  type?: string;
  export_type?: string;
  source_type?: string;
  [key: string]: unknown;
};

export type Model = {
  id: string;
  object: string;
  created: number;
  owned_by: string;
  permission: unknown[];
  root: string;
  parent: string | null;
};

type AccountListResponse = {
  items: Account[];
  /** 6.3：服务端分页时返回账号总数（默认全量返回也带 total，兼容旧字段）。 */
  total?: number;
};

type ModelListResponse = {
  object: string;
  data: Model[];
};

type AccountMutationResponse = {
  items: Account[];
  added?: number;
  skipped?: number;
  removed?: number;
  refreshed?: number;
  relogined?: number;
  errors?: Array<{ access_token: string; error: string }>;
};

export type AccountRefreshResponse = {
  items: Account[];
  refreshed: number;
  relogined?: number;
  errors: Array<{ access_token: string; error: string }>;
};

export type RefreshProgressResponse = {
  total: number;
  processed: number;
  done: boolean;
  error: string | null;
  status_counts?: Record<string, number>;
  total_quota?: number;
  result?: AccountRefreshResponse | null;
  results?: Array<{ token: string; status: string; error?: string | null }>;
};

type AccountUpdateResponse = {
  item: Account;
  items: Account[];
};

export type ProxyRuntimeEgressMode = "direct" | "single_proxy";
export type ProxyRuntimeClearanceMode = "none" | "manual" | "flaresolverr";

export type ProxyRuntimeClearanceSettings = {
  enabled: boolean;
  mode: ProxyRuntimeClearanceMode;
  cf_cookies: string;
  cf_clearance: string;
  user_agent: string;
  browser: string;
  flaresolverr_url: string;
  timeout_sec: number | string;
  refresh_interval: number | string;
  warm_up_on_start: boolean;
  has_cf_cookies?: boolean;
  has_cf_clearance?: boolean;
};

export type ProxyRuntimeSettings = {
  enabled: boolean;
  egress_mode: ProxyRuntimeEgressMode;
  proxy_url: string;
  resource_proxy_url: string;
  skip_ssl_verify: boolean;
  reset_session_status_codes: number[];
  clearance: ProxyRuntimeClearanceSettings;
};

export type ProxyRuntimeStatus = {
  enabled: boolean;
  egress_mode: ProxyRuntimeEgressMode | string;
  proxy_source: string;
  has_proxy: boolean;
  clearance_enabled: boolean;
  clearance_mode: ProxyRuntimeClearanceMode | string;
  has_clearance_bundle: boolean;
  cached_clearance_hosts: string[];
};

export type ProxyRuntimeResponse = {
  runtime: ProxyRuntimeSettings;
  status: ProxyRuntimeStatus;
};

export type SettingsConfig = {
  proxy: string;
  base_url?: string;
  global_system_prompt?: string;
  default_upstream_model_name?: string;
  default_thinking_effort?: "auto" | "standard" | "extended" | "max";
  sensitive_words?: string[];
  ai_review?: {
    enabled?: boolean;
    base_url?: string;
    api_key?: string;
    model?: string;
    prompt?: string;
  };
  refresh_account_interval_minute?: number | string;
  image_retention_days?: number | string;
  image_poll_timeout_secs?: number | string;
  image_poll_interval_secs?: number | string;
  image_poll_initial_wait_secs?: number | string;
  image_min_free_mb?: number | string;
  chat_completion_cache?: Record<string, unknown>;
  image_account_concurrency?: number | string;
  image_parallel_generation?: boolean;
  image_settle_enabled?: boolean;
  image_check_before_hit_enabled?: boolean;
  image_remove_conversation_after_result?: boolean;
  image_remove_conversation_always?: boolean;
  image_settle_secs?: number | string;
  image_timeout_retry_secs?: number | string;
  auto_remove_invalid_accounts?: boolean;
  auto_remove_rate_limited_accounts?: boolean;
  auto_relogin_after_refresh?: boolean;
  log_levels?: string[];
  scheduler_mode?: "round_robin" | "remaining_quota" | "weighted_random";
  scheduler_priority?: Record<string, number>;
  proactive_probe_enabled?: boolean;
  proactive_probe_interval_minute?: number;
  rate_limit_rpm?: number;
  rate_limit_per_ip_rpm?: number;
  workers?: number;
  sqlite_wal_mode?: boolean;
  sqlite_busy_timeout_ms?: number;
  progress_ttl_seconds?: number;
  ssrf_allow_private_ips?: boolean;
  trusted_proxies?: string[];
  alert_webhook_url?: string;
  alert_webhook_timeout?: number;
  alert_events?: string[];
  image_storage?: ImageStorageSettings;
  proxy_runtime?: ProxyRuntimeSettings;
  backup?: BackupSettings;
  backup_state?: BackupState;
  [key: string]: unknown;
};

export type BackupInclude = {
  config: boolean;
  cpa: boolean;
  sub2api: boolean;
  logs: boolean;
  image_tasks: boolean;
  accounts_snapshot: boolean;
  auth_keys_snapshot: boolean;
  images: boolean;
};

export type BackupSettings = {
  enabled: boolean;
  provider: "cloudflare_r2" | string;
  account_id: string;
  access_key_id: string;
  secret_access_key: string;
  bucket: string;
  prefix: string;
  interval_minutes: number | string;
  rotation_keep: number | string;
  encrypt: boolean;
  passphrase: string;
  include: BackupInclude;
};

export type BackupState = {
  running: boolean;
  last_started_at?: string | null;
  last_finished_at?: string | null;
  last_status?: string;
  last_error?: string | null;
  last_object_key?: string | null;
};

export type BackupItem = {
  key: string;
  name: string;
  size: number;
  updated_at?: string | null;
  encrypted: boolean;
};

export type BackupDetail = {
  key: string;
  name: string;
  encrypted: boolean;
  created_at?: string | null;
  trigger?: string | null;
  app_version?: string | null;
  storage_backend?: Record<string, unknown> | null;
  files: Array<{
    name: string;
    exists: boolean;
    content_type?: string;
    size: number;
    sha256?: string;
  }>;
  snapshots: Array<{
    name: string;
    count: number;
  }>;
};

export type ManagedImage = {
  rel: string;
  path?: string;
  name: string;
  date: string;
  size: number;
  url: string;
  thumbnail_url?: string;
  created_at: string;
  width?: number;
  height?: number;
  tags?: string[];
};

export type SystemLog = {
  id: string;
  time: string;
  type: "call" | "account" | string;
  summary?: string;
  detail?: Record<string, unknown>;
  [key: string]: unknown;
};

export type AuditLog = {
  id: string;
  ts: string;
  action: string;
  result: string;
  operator: string;
  resource?: string;
  detail?: Record<string, unknown>;
  request_id?: string;
  ip?: string;
  method?: string;
};

export type ImageResponse = {
  created: number;
  data: Array<{ b64_json?: string; url?: string; revised_prompt?: string }>;
};

export type ImageTask = {
  id: string;
  status: "queued" | "running" | "success" | "error";
  mode: "generate" | "edit";
  model?: ImageModel;
  size?: string;
  quality?: string;
  created_at: string;
  updated_at: string;
  conversation_id?: string;
  data?: Array<{ b64_json?: string; url?: string; revised_prompt?: string }>;
  error?: string;
  progress?: string;
  elapsed_secs?: number;
  duration_ms?: number;
};

type ImageTaskListResponse = {
  items: ImageTask[];
  missing_ids: string[];
};

export type LoginResponse = {
  ok: boolean;
  version: string;
  role: AuthRole;
  subject_id: string;
  name: string;
};

export type UserKey = {
  id: string;
  name: string;
  role: "user";
  enabled: boolean;
  created_at: string | null;
  last_used_at: string | null;
};

export async function login(authKey: string) {
  const normalizedAuthKey = String(authKey || "").trim();
  return httpRequest<LoginResponse>("/auth/login", {
    method: "POST",
    body: {},
    headers: {
      Authorization: `Bearer ${normalizedAuthKey}`,
    },
    redirectOnUnauthorized: false,
  });
}

export type ProviderInfo = {
  name: string;
  display_name: string;
  enabled: boolean;
  description: string;
};

type ProviderListResponse = {
  providers: ProviderInfo[];
};

export async function fetchAccounts(provider?: string) {
  const params = provider ? `?provider=${encodeURIComponent(provider)}` : "";
  return httpRequest<AccountListResponse>(`/api/accounts${params}`);
}

export async function fetchProviders() {
  return httpRequest<ProviderListResponse>("/api/providers");
}

export async function fetchModels() {
  return httpRequest<ModelListResponse>("/v1/models");
}

export async function createAccounts(tokens: string[], accounts: AccountImportPayload[] = []) {
  return httpRequest<AccountMutationResponse>("/api/accounts", {
    method: "POST",
    body: { tokens, accounts },
  });
}

export type OAuthLoginStartResponse = {
  session_id: string;
  authorize_url: string;
  expires_in: string;
  redirect_uri_prefix: string;
};

export async function startOAuthLogin(emailHint?: string) {
  return httpRequest<OAuthLoginStartResponse>("/api/accounts/oauth/start", {
    method: "POST",
    body: { email_hint: emailHint ?? "" },
  });
}

export async function finishOAuthLogin(sessionId: string, callback: string) {
  return httpRequest<AccountMutationResponse>("/api/accounts/oauth/finish", {
    method: "POST",
    body: { session_id: sessionId, callback },
  });
}

export async function deleteAccounts(tokens: string[]) {
  return httpRequest<AccountMutationResponse>("/api/accounts", {
    method: "DELETE",
    body: { tokens },
  });
}

/** 批量驱逐失效 token（状态为「异常」的账号），返回处理数量。 */
export async function evictStaleAccounts() {
  return httpRequest<{ stale: number; evicted: number }>("/api/accounts/evict_stale", {
    method: "POST",
    body: {},
  });
}

/** 3.1.2：批量操作表驱动分发（evict_stale / label / export），按选中 ids。 */
export type AccountBatchAction = "evict_stale" | "label" | "export";
export async function batchAccounts(action: AccountBatchAction, ids: string[], label = "") {
  return httpRequest<
    { action: string; processed: number; evicted?: number; updated?: number; count?: number; items?: unknown[] }
  >("/api/accounts/batch", {
    method: "POST",
    body: { action, ids, label },
  });
}

/** 熔断状态：token 末 8 位 -> 熔断器状态（仅含非 closed 账号）。 */
export type CircuitBreakerStatus = {
  breakers: Record<string, { state: string; recover_in_seconds: number }>;
  total_open: number;
};

export async function fetchCircuitBreakers() {
  return httpRequest<CircuitBreakerStatus>("/api/dashboard/circuit_breakers");
}

export async function refreshAccounts(accessTokens: string[]) {
  return httpRequest<{ progress_id: string }>("/api/accounts/refresh", {
    method: "POST",
    body: { access_tokens: accessTokens },
  });
}

export async function fetchRefreshProgress(progressId: string) {
  return httpRequest<RefreshProgressResponse>(`/api/accounts/refresh/progress/${progressId}`);
}

export async function reLoginAccounts(accessTokens: string[]) {
  return httpRequest<{ progress_id: string }>("/api/accounts/re-login", {
    method: "POST",
    body: { access_tokens: accessTokens },
  });
}

/** v2.9.0：自动恢复异常账号（refresh_token 换 token + 密码重登兜底，同步返回）。 */
export async function recoverAbnormalAccounts(accessTokens: string[]) {
  return httpRequest<{
    recovered: number;
    failed: number;
    skipped: number;
    password_relogin_triggered: number;
    items: Account[];
  }>("/api/accounts/recover", {
    method: "POST",
    body: { access_tokens: accessTokens },
  });
}

export async function fetchReLoginProgress(progressId: string) {
  return httpRequest<RefreshProgressResponse>(`/api/accounts/re-login/progress/${progressId}`);
}

export async function updateAccount(
  accessToken: string,
  updates: {
    type?: AccountType;
    status?: AccountStatus;
    quota?: number;
    proxy?: string;
  },
) {
  return httpRequest<AccountUpdateResponse>("/api/accounts/update", {
    method: "POST",
    body: {
      access_token: accessToken,
      ...updates,
    },
  });
}

export async function generateImage(prompt: string, model?: ImageModel, size?: string, quality = "auto") {
  return httpRequest<ImageResponse>(
    "/v1/images/generations",
    {
      method: "POST",
      body: {
        prompt,
        ...(model ? { model } : {}),
        ...(size ? { size } : {}),
        quality,
        n: 1,
        response_format: "b64_json",
      },
    },
  );
}

export async function editImage(files: File | File[], prompt: string, model?: ImageModel, size?: string, quality = "auto") {
  const formData = new FormData();
  const uploadFiles = Array.isArray(files) ? files : [files];

  uploadFiles.forEach((file) => {
    formData.append("image", file);
  });
  formData.append("prompt", prompt);
  if (model) {
    formData.append("model", model);
  }
  if (size) {
    formData.append("size", size);
  }
  formData.append("quality", quality);
  formData.append("n", "1");

  return httpRequest<ImageResponse>(
    "/v1/images/edits",
    {
      method: "POST",
      body: formData,
    },
  );
}

export async function createImageGenerationTask(
  clientTaskId: string,
  prompt: string,
  model?: ImageModel,
  size?: string,
  quality = "auto",
  seed?: number,
) {
  return httpRequest<ImageTask>("/api/image-tasks/generations", {
    method: "POST",
    body: {
      client_task_id: clientTaskId,
      prompt,
      ...(model ? { model } : {}),
      ...(size ? { size } : {}),
      quality,
      ...(seed !== undefined ? { seed } : {}),
    },
  });
}

export async function createImageEditTask(
  clientTaskId: string,
  files: File | File[],
  prompt: string,
  model?: ImageModel,
  size?: string,
  quality = "auto",
  seed?: number,
) {
  const formData = new FormData();
  const uploadFiles = Array.isArray(files) ? files : [files];

  uploadFiles.forEach((file) => {
    formData.append("image", file);
  });
  formData.append("client_task_id", clientTaskId);
  formData.append("prompt", prompt);
  if (model) {
    formData.append("model", model);
  }
  if (size) {
    formData.append("size", size);
  }
  formData.append("quality", quality);
  if (seed !== undefined) {
    formData.append("seed", String(seed));
  }

  return httpRequest<ImageTask>("/api/image-tasks/edits", {
    method: "POST",
    body: formData,
  });
}

export async function fetchImageTasks(ids: string[]) {
  const params = new URLSearchParams();
  if (ids.length > 0) {
    params.set("ids", ids.join(","));
  }
  params.set("_t", String(Date.now()));
  return httpRequest<ImageTaskListResponse>(`/api/image-tasks?${params.toString()}`);
}

export async function resumeImagePoll(taskId: string, extraTimeoutSecs = 30) {
  return httpRequest<ImageTask>(`/api/image-tasks/${encodeURIComponent(taskId)}/resume-poll`, {
    method: "POST",
    body: { extra_timeout_secs: extraTimeoutSecs },
  });
}

export async function fetchSettingsConfig() {
  return httpRequest<{ config: SettingsConfig }>("/api/settings");
}

export async function updateSettingsConfig(settings: SettingsConfig) {
  return httpRequest<{ config: SettingsConfig }>("/api/settings", {
    method: "POST",
    body: settings,
  });
}

export async function testBackupConnection() {
  return httpRequest<{ result: { ok: boolean; status: number } }>("/api/backup/test", {
    method: "POST",
    body: {},
  });
}

export async function testImageStorageConnection() {
  return httpRequest<{ result: { ok: boolean; status: number; error?: string } }>("/api/image-storage/test", {
    method: "POST",
    body: {},
  });
}

export async function syncImageStorage() {
  return httpRequest<{ result: { uploaded: number; skipped: number; failed: number } }>("/api/image-storage/sync", {
    method: "POST",
    body: {},
  });
}

export async function fetchBackups() {
  return httpRequest<{ items: BackupItem[]; state: BackupState; settings: BackupSettings }>("/api/backups");
}

export async function runBackupNow() {
  return httpRequest<{ result: { key: string; size: number; encrypted: boolean } }>("/api/backups/run", {
    method: "POST",
    body: {},
  });
}

export async function deleteBackup(key: string) {
  return httpRequest<{ ok: boolean }>("/api/backups/delete", {
    method: "POST",
    body: { key },
  });
}

export async function fetchBackupDetail(key: string) {
  const params = new URLSearchParams();
  params.set("key", key);
  return httpRequest<{ item: BackupDetail }>(`/api/backups/detail?${params.toString()}`);
}

export function getBackupDownloadUrl(key: string) {
  const params = new URLSearchParams();
  params.set("key", key);
  return `/api/backups/download?${params.toString()}`;
}

export async function fetchManagedImages(filters: { start_date?: string; end_date?: string }) {
  const params = new URLSearchParams();
  if (filters.start_date) params.set("start_date", filters.start_date);
  if (filters.end_date) params.set("end_date", filters.end_date);
  return httpRequest<{ items: ManagedImage[]; groups: Array<{ date: string; items: ManagedImage[] }> }>(
    `/api/images${params.toString() ? `?${params.toString()}` : ""}`,
  );
}

export async function deleteManagedImages(body: { paths?: string[]; start_date?: string; end_date?: string; all_matching?: boolean }) {
  return httpRequest<{ removed: number }>("/api/images/delete", { method: "POST", body });
}

export async function downloadImages(paths: string[]) {
  const response = await request.post("/api/images/download", { paths }, { responseType: "blob" });
  const blob = response.data as Blob;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "images.zip";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// C-P0：导出账号走后端 /api/accounts/export（含 refresh_token/id_token 三件套 + zip/json），
// 修复此前前端纯客户端裸 access_token 下载导致的"假导出"死代码
export async function exportAccounts(accessTokens: string[], format: "json" | "zip") {
  let response;
  try {
    response = await request.post(
      "/api/accounts/export",
      { access_tokens: accessTokens, format },
      { responseType: "blob" },
    );
  } catch (error) {
    // P3-8：blob 响应下 400 错误体（"没有可导出的完整账号…"）以 Blob 形式存在，
    // 拦截器 errorMessageFromValue 解析不到 → toast 只显示通用 status。这里解析 Blob 文本还原真实原因。
    const axiosErr = error as { response?: { status?: number; data?: unknown } };
    if (axiosErr.response?.status === 400 && axiosErr.response.data instanceof Blob) {
      const text = await axiosErr.response.data.text();
      throw new Error(text || "导出失败：没有可导出的完整账号");
    }
    throw error;
  }
  const blob = response.data as Blob;
  const disposition = String(response.headers?.["content-disposition"] || "");
  const match = disposition.match(/filename="?([^";]+)"?/);
  const filename = match ? match[1] : `codex-accounts-${Date.now()}.${format}`;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export async function downloadSingleImage(path: string) {
  const response = await request.get(`/api/images/download/${path}`, { responseType: "blob" });
  const blob = response.data as Blob;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = path.split("/").pop() || "image.png";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export async function fetchImageTags() {
  return httpRequest<{ tags: string[] }>("/api/images/tags");
}

export async function setImageTags(path: string, tags: string[]) {
  return httpRequest<{ ok: boolean; tags: string[] }>("/api/images/tags", {
    method: "POST",
    body: { path, tags },
  });
}

export async function deleteImageTag(tag: string) {
  return httpRequest<{ ok: boolean; removed_from: number }>(`/api/images/tags/${encodeURIComponent(tag)}`, {
    method: "DELETE",
  });
}

export type ImageStorageStats = {
  disk_total_mb: number; disk_used_mb: number; disk_free_mb: number;
  image_count: number; image_size_mb: number; image_size_bytes: number;
};

export async function fetchImageStorage() {
  return httpRequest<ImageStorageStats>("/api/images/storage");
}

export async function compressAllImages() {
  return httpRequest<{ compressed: number; saved_bytes: number; saved_mb: number }>("/api/images/storage/compress", { method: "POST" });
}

export async function deleteToTarget(targetFreeMb: number) {
  return httpRequest<{ removed: number; freed_mb: number; done: boolean }>(
    `/api/images/storage/cleanup-to-target?target_free_mb=${targetFreeMb}&dry_run=false`,
    { method: "POST" },
  );
}

export async function fetchSystemLogs(filters: { type?: string; start_date?: string; end_date?: string; account_email?: string; days?: number }) {
  const params = new URLSearchParams();
  if (filters.type) params.set("type", filters.type);
  if (filters.start_date) params.set("start_date", filters.start_date);
  if (filters.end_date) params.set("end_date", filters.end_date);
  if (filters.account_email) params.set("account_email", filters.account_email);
  if (filters.days !== undefined) params.set("days", String(filters.days));
  return httpRequest<{ items: SystemLog[] }>(`/api/logs${params.toString() ? `?${params.toString()}` : ""}`);
}

export async function deleteSystemLogs(ids: string[]) {
  return httpRequest<{ removed: number }>("/api/logs/delete", {
    method: "POST",
    body: { ids },
  });
}

export async function fetchAuditLogs(filters: { days?: number; result?: string; operator?: string; limit?: number }) {
  const params = new URLSearchParams();
  if (filters.days !== undefined) params.set("days", String(filters.days));
  if (filters.result) params.set("result", filters.result);
  if (filters.operator) params.set("operator", filters.operator);
  if (filters.limit !== undefined) params.set("limit", String(filters.limit));
  return httpRequest<{ items: AuditLog[] }>(`/api/audit${params.toString() ? `?${params.toString()}` : ""}`);
}

export async function fetchUserKeys() {
  return httpRequest<{ items: UserKey[] }>("/api/auth/users");
}

export async function createUserKey(name: string) {
  return httpRequest<{ item: UserKey; key: string; items: UserKey[] }>("/api/auth/users", {
    method: "POST",
    body: { name },
  });
}

export async function updateUserKey(keyId: string, updates: { enabled?: boolean; name?: string; key?: string }) {
  return httpRequest<{ item: UserKey; items: UserKey[] }>(`/api/auth/users/${keyId}`, {
    method: "POST",
    body: updates,
  });
}

export async function deleteUserKey(keyId: string) {
  return httpRequest<{ items: UserKey[] }>(`/api/auth/users/${keyId}`, {
    method: "DELETE",
  });
}

// ── CPA (CLIProxyAPI) ──────────────────────────────────────────────

export type CPAPool = {
  id: string;
  name: string;
  base_url: string;
  import_job?: CPAImportJob | null;
};

export type CPARemoteFile = {
  name: string;
  email: string;
};

export type CPAImportJob = {
  job_id: string;
  status: "pending" | "running" | "completed" | "failed";
  created_at: string;
  updated_at: string;
  total: number;
  completed: number;
  added: number;
  skipped: number;
  refreshed: number;
  failed: number;
  errors: Array<{ name: string; error: string }>;
};

export async function fetchCPAPools() {
  return httpRequest<{ pools: CPAPool[] }>("/api/cpa/pools");
}

export async function createCPAPool(pool: { name: string; base_url: string; secret_key: string }) {
  return httpRequest<{ pool: CPAPool; pools: CPAPool[] }>("/api/cpa/pools", {
    method: "POST",
    body: pool,
  });
}

export async function updateCPAPool(
  poolId: string,
  updates: { name?: string; base_url?: string; secret_key?: string },
) {
  return httpRequest<{ pool: CPAPool; pools: CPAPool[] }>(`/api/cpa/pools/${poolId}`, {
    method: "POST",
    body: updates,
  });
}

export async function deleteCPAPool(poolId: string) {
  return httpRequest<{ pools: CPAPool[] }>(`/api/cpa/pools/${poolId}`, {
    method: "DELETE",
  });
}

export async function fetchCPAPoolFiles(poolId: string) {
  return httpRequest<{ pool_id: string; files: CPARemoteFile[] }>(`/api/cpa/pools/${poolId}/files`);
}

export async function startCPAImport(poolId: string, names: string[]) {
  return httpRequest<{ import_job: CPAImportJob | null }>(`/api/cpa/pools/${poolId}/import`, {
    method: "POST",
    body: { names },
  });
}

export async function fetchCPAPoolImportJob(poolId: string) {
  return httpRequest<{ import_job: CPAImportJob | null }>(`/api/cpa/pools/${poolId}/import`);
}

// ── Sub2API ────────────────────────────────────────────────────────

export type Sub2APIServer = {
  id: string;
  name: string;
  base_url: string;
  email: string;
  has_api_key: boolean;
  group_id: string;
  import_job?: CPAImportJob | null;
};

export type Sub2APIRemoteAccount = {
  id: string;
  name: string;
  email: string;
  plan_type: string;
  status: string;
  expires_at: string;
  has_refresh_token: boolean;
};

export type Sub2APIRemoteGroup = {
  id: string;
  name: string;
  description: string;
  platform: string;
  status: string;
  account_count: number;
  active_account_count: number;
};

export async function fetchSub2APIServers() {
  return httpRequest<{ servers: Sub2APIServer[] }>("/api/sub2api/servers");
}

export async function createSub2APIServer(server: {
  name: string;
  base_url: string;
  email: string;
  password: string;
  api_key: string;
  group_id: string;
}) {
  return httpRequest<{ server: Sub2APIServer; servers: Sub2APIServer[] }>("/api/sub2api/servers", {
    method: "POST",
    body: server,
  });
}

export async function updateSub2APIServer(
  serverId: string,
  updates: {
    name?: string;
    base_url?: string;
    email?: string;
    password?: string;
    api_key?: string;
    group_id?: string;
  },
) {
  return httpRequest<{ server: Sub2APIServer; servers: Sub2APIServer[] }>(`/api/sub2api/servers/${serverId}`, {
    method: "POST",
    body: updates,
  });
}

export async function fetchSub2APIServerGroups(serverId: string) {
  return httpRequest<{ server_id: string; groups: Sub2APIRemoteGroup[] }>(
    `/api/sub2api/servers/${serverId}/groups`,
  );
}

export async function deleteSub2APIServer(serverId: string) {
  return httpRequest<{ servers: Sub2APIServer[] }>(`/api/sub2api/servers/${serverId}`, {
    method: "DELETE",
  });
}

export async function fetchSub2APIServerAccounts(serverId: string) {
  return httpRequest<{ server_id: string; accounts: Sub2APIRemoteAccount[] }>(
    `/api/sub2api/servers/${serverId}/accounts`,
  );
}

export async function startSub2APIImport(serverId: string, accountIds: string[]) {
  return httpRequest<{ import_job: CPAImportJob | null }>(`/api/sub2api/servers/${serverId}/import`, {
    method: "POST",
    body: { account_ids: accountIds },
  });
}

export async function fetchSub2APIImportJob(serverId: string) {
  return httpRequest<{ import_job: CPAImportJob | null }>(`/api/sub2api/servers/${serverId}/import`);
}

// ── Upstream proxy ────────────────────────────────────────────────

export type ProxySettings = {
  enabled: boolean;
  url: string;
};

export type ProxyTestResult = {
  ok: boolean;
  status: number;
  latency_ms: number;
  error: string | null;
  proxy_source?: string;
  has_proxy?: boolean;
};

export type ClearanceTestResult = {
  ok: boolean;
  status: string;
  latency_ms: number;
  has_cookies: boolean;
  user_agent: string;
  error: string | null;
  runtime: ProxyRuntimeStatus;
};

// 注意：历史上曾存在 GET/POST /api/proxy（fetchProxy/updateProxy），后端从未注册该路由——
// 属断链死代码，已随孤儿组件 proxy-settings.tsx 一并移除（第七轮审计）。
// 代理配置真实链路：config-card 的 proxy 字段走 POST /api/settings；运行时走 /api/proxy/runtime。

export async function testProxy(url?: string) {
  return httpRequest<{ result: ProxyTestResult }>("/api/proxy/test", {
    method: "POST",
    body: { url: url ?? "" },
  });
}

export async function fetchProxyRuntime() {
  return httpRequest<ProxyRuntimeResponse>("/api/proxy/runtime");
}

export async function updateProxyRuntime(runtime: ProxyRuntimeSettings) {
  return httpRequest<ProxyRuntimeResponse>("/api/proxy/runtime", {
    method: "POST",
    body: runtime,
  });
}

export async function testProxyClearance(targetUrl?: string) {
  return httpRequest<{ result: ClearanceTestResult }>("/api/proxy/clearance/test", {
    method: "POST",
    body: { target_url: targetUrl ?? "https://chatgpt.com" },
  });
}

// ---------- 调度看板 / 运维概览 / 用量统计 ----------

export type SchedulerTier = "healthy" | "warm" | "risky" | "banned";

export type SchedulerAccount = {
  email?: string | null;
  type?: string;
  status?: string;
  quota: number;
  success: number;
  fail: number;
  image_inflight: number;
  tier: SchedulerTier;
  score: number;
  priority: number;
  lifetime_risk?: "low" | "medium" | "high" | "critical";
  lifetime_eta_days?: number | null;
  lifetime_score?: number;
};

export type SchedulerDashboard = {
  health: {
    tiers: Record<SchedulerTier, number>;
    statuses: Record<string, number>;
    total: number;
    total_quota: number;
    total_inflight: number;
  };
  accounts: SchedulerAccount[];
  provider_stats?: Array<{
    name: string;
    display_name: string;
    enabled: boolean;
    total_accounts: number;
    available_accounts: number;
    tiers: Record<string, number>;
  }>;
};

export type OpsOverview = {
  platform: string;
  python: string;
  pid: number;
  uptime_seconds: number;
  cpu_percent: number;
  memory_used_mb: number | null;
  memory_total_mb: number | null;
  disk_free_mb: number;
  disk_total_mb: number;
  storage: {
    disk_total_mb: number;
    disk_used_mb: number;
    disk_free_mb: number;
    image_count: number;
    image_size_mb: number;
    image_size_bytes: number;
  };
  scheduler_mode: string;
  refresh_account_interval_minute: number;
  image_account_concurrency: number;
  backup?: {
    configured: boolean;
    running: boolean;
    last_status: string;
    last_finished_at?: string | null;
    last_error?: string | null;
  };
};

export type UsageStats = {
  success_24h: number;
  failed_24h: number;
  total_24h: number;
  by_summary: Record<string, number>;
  recent: Array<{ time: string; summary: string; status: string }>;
  hours?: number;
};

export function fetchSchedulerDashboard() {
  return httpRequest<SchedulerDashboard>("/api/dashboard/scheduler");
}

export function fetchOpsOverview() {
  return httpRequest<OpsOverview>("/api/dashboard/ops");
}

export function fetchUsageStats(hours?: number) {
  const params = hours && hours !== 24 ? `?hours=${hours}` : "";
  return httpRequest<UsageStats>(`/api/dashboard/usage${params}`);
}

export type UsageForecast = {
  status: "ok" | "insufficient_data" | "unlimited" | "exhausted";
  daily_avg_consumption: number;
  total_remaining_quota: number;
  quota_accounts: number;
  window_days: number;
  daily_series: Array<{ date: string; calls: number }>;
  days_until_depletion: number | null;
  estimated_depletion_date: string | null;
  should_alert: boolean;
  alert_threshold_days: number;
};

export function fetchUsageForecast() {
  return httpRequest<UsageForecast>("/api/dashboard/usage-forecast");
}

// ---------- 延迟统计 / 连接池并发 ----------

export type LatencyPathStats = {
  count: number;
  errors: number;
  avg_latency_ms: number;
  error_rate: number;
  statuses: Record<string, number>;
};

export type LatencySummary = {
  total_requests: number;
  total_errors: number;
  avg_latency_ms: number;
  error_rate: number;
  uptime_seconds: number;
  by_path: Record<string, LatencyPathStats>;
  inflight: Record<string, number>;
};

export function fetchLatencySummary() {
  return httpRequest<LatencySummary>("/api/dashboard/latency");
}

export type MetricsSummary = {
  request_rate: number;
  error_rate: number;
  p95_latency_ms: number;
  avg_latency_ms: number;
  total_requests: number;
  total_errors: number;
};

export function fetchMetricsSummary() {
  return httpRequest<MetricsSummary>("/api/dashboard/metrics_summary");
}

/** v2.9.0：拉取 IP 池列表（账号编辑弹窗"从池选 IP"用）。 */
export function fetchProxies() {
  return httpRequest<{ proxies: { url: string; host?: string; country?: string }[] }>("/api/proxies");
}

/** kookeey 粘性出口探测结果。 */
export interface KookeeyEgressResult {
  ok: boolean;
  enabled?: boolean;
  ip?: string;
  session?: string;
  email?: string;
  error?: string;
}

/** v2.9.0：探测指定邮箱账号经 kookeey 粘性住宅代理的真实出口 IP。 */
export function probeKookeeyEgress(email: string) {
  return httpRequest<KookeeyEgressResult>("/api/proxies/kookeey-egress", {
    method: "POST",
    body: { email },
  });
}

// ──────────────────────── kookeey 流量/账号看板 ────────────────────────

export interface KookeeyConfig {
  enabled: boolean;
  extract_url?: string;
  developer_token?: string;
  access_id?: string;
  default_country?: string;
  default_count?: number;
}

export interface KookeeyTraffic {
  ok: boolean;
  need_config?: boolean;
  balance_mb?: number | null;
  today_use_mb?: number | null;
  month_use_mb?: number | null;
  package?: {
    traffic_left_gb?: number | null;
    traffic_total_gb?: number | null;
    thread_left?: number | null;
    thread_total?: number | null;
    expire_time?: number | null;
    name?: string | null;
  };
  package_error?: string;
  error?: string;
}

export interface KookeeyIpUsageRow {
  email: string;
  session: string;
  requests: number;
  fail: number;
  total_bytes: number;
  estimated_mb: number;
  last_used_at: string;
  last_ip: string;
  last_probe_at: string;
}

export interface KookeeyIpUsageBoard {
  used_ip_count: number;
  total_extracted: number;
  total_bytes: number;
  estimated_mb: number;
  leaderboard: KookeeyIpUsageRow[];
}

export interface KookeeyProbeResult {
  probed: number;
  ok: number;
  failed: number;
  duration_s: number;
}

export function fetchKookeeyConfig() {
  return httpRequest<KookeeyConfig>("/api/kookeey/config");
}

export function updateKookeeyConfig(cfg: KookeeyConfig) {
  return httpRequest<{ ok: boolean; config: KookeeyConfig }>("/api/kookeey/config", {
    method: "POST",
    body: cfg,
  });
}

export function fetchKookeeyTraffic() {
  return httpRequest<KookeeyTraffic>("/api/kookeey/traffic");
}

export function fetchKookeeyIpUsage() {
  return httpRequest<KookeeyIpUsageBoard>("/api/kookeey/ip-usage");
}

export function probeKookeeyIps() {
  return httpRequest<KookeeyProbeResult>("/api/kookeey/probe-ips", { method: "POST" });
}

export interface KookeeyExtractResult {
  ok: boolean;
  extracted: number;
  imported: number;
  deduped: number;
  skipped: number;
  country: string;
  error?: string;
}

export function extractKookeey(country?: string, count?: number) {
  return httpRequest<KookeeyExtractResult>("/api/kookeey/extract", {
    method: "POST",
    body: { country: country ?? "", count: count ?? 0 },
  });
}
