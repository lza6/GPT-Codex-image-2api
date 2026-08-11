/**
 * chatgpt2api SDK — 自动生成 (v2.28.0)
 *
 * 用法：
 *   const client = new Chatgpt2apiClient('/', 'your-api-key');
 *   const models = await client.listModels();
 */

export class Chatgpt2apiClient {
  VERSION = "2.28.0";

  constructor(baseUrl = "/", apiKey = null) {
    this.baseUrl = baseUrl.replace(/\/$/, "");
    this.headers = {
      "Content-Type": "application/json",
    };
    if (apiKey) {
      this.headers["Authorization"] = `Bearer ${apiKey}`;
    }
  }

  async request(method, path, options = {}) {
    const url = `${this.baseUrl}${path}`;
    const opts = {
      method,
      headers: { ...this.headers },
    };
    if (options.body) {
      opts.body = JSON.stringify(options.body);
    }
    if (options.params) {
      const qs = new URLSearchParams(options.params).toString();
      if (qs) path += `?${qs}`;
    }
    const resp = await fetch(url, opts);
    if (!resp.ok) {
      const err = await resp.text().catch(() => "");
      throw new Error(`HTTP ${resp.status}: ${err}`);
    }
    const ct = resp.headers.get("content-type") || "";
    if (ct.includes("application/json")) {
      return resp.json();
    }
    return resp.text();
  }

  // --- AI ---

  /** List Models */
  async listModelsV1ModelsGet() {
    const path = `/v1/models`;
    const params = { refresh };
    return this.request('GET', path, { params: params });
  }

  /** Generate Images */
  async generateImagesV1ImagesGenerationsPost() {
    const path = `/v1/images/generations`;
    return this.request('POST', path, { body });
  }

  /** Edit Images */
  async editImagesV1ImagesEditsPost() {
    const path = `/v1/images/edits`;
    return this.request('POST', path);
  }

  /** Create Chat Completion */
  async createChatCompletionV1ChatCompletionsPost() {
    const path = `/v1/chat/completions`;
    return this.request('POST', path, { body });
  }

  /** Create Response */
  async createResponseV1ResponsesPost() {
    const path = `/v1/responses`;
    return this.request('POST', path, { body });
  }

  /** Create Message */
  async createMessageV1MessagesPost() {
    const path = `/v1/messages`;
    return this.request('POST', path, { body });
  }

  /** Search */
  async searchV1SearchPost() {
    const path = `/v1/search`;
    return this.request('POST', path, { body });
  }

  /** List Editable File Tasks */
  async listEditableFileTasksV1EditableFileTasksGet() {
    const path = `/v1/editable-file-tasks`;
    const params = { ids };
    return this.request('GET', path, { params: params });
  }

  /** Download Editable File */
  async downloadEditableFileFilesFilePathGet(file_path) {
    const path = `/files/${file_path}`;
    return this.request('GET', path);
  }

  /** Create Ppt Task */
  async createPptTaskV1PptGenerationsPost() {
    const path = `/v1/ppt/generations`;
    return this.request('POST', path, { body });
  }

  /** Create Psd Task */
  async createPsdTaskV1PsdGenerationsPost() {
    const path = `/v1/psd/generations`;
    return this.request('POST', path, { body });
  }

  // --- Accounts ---

  /** List User Keys */
  async listUserKeysApiAuthUsersGet() {
    const path = `/api/auth/users`;
    return this.request('GET', path);
  }

  /** Create User Key */
  async createUserKeyApiAuthUsersPost() {
    const path = `/api/auth/users`;
    return this.request('POST', path, { body });
  }

  /** Update User Key */
  async updateUserKeyApiAuthUsersKeyIdPost(key_id) {
    const path = `/api/auth/users/${key_id}`;
    return this.request('POST', path, { body });
  }

  /** Delete User Key */
  async deleteUserKeyApiAuthUsersKeyIdDelete(key_id) {
    const path = `/api/auth/users/${key_id}`;
    return this.request('DELETE', path);
  }

  /** Get Accounts */
  async getAccountsApiAccountsGet() {
    const path = `/api/accounts`;
    const params = { page, page_size, provider, refresh };
    return this.request('GET', path, { params: params });
  }

  /** Create Accounts */
  async createAccountsApiAccountsPost() {
    const path = `/api/accounts`;
    return this.request('POST', path, { body });
  }

  /** Delete Accounts */
  async deleteAccountsApiAccountsDelete() {
    const path = `/api/accounts`;
    return this.request('DELETE', path, { body });
  }

  /** Refresh Accounts */
  async refreshAccountsApiAccountsRefreshPost() {
    const path = `/api/accounts/refresh`;
    return this.request('POST', path, { body });
  }

  /** Get Refresh Progress */
  async getRefreshProgressApiAccountsRefreshProgressProgressIdGet(progress_id) {
    const path = `/api/accounts/refresh/progress/${progress_id}`;
    return this.request('GET', path);
  }

  /** Re Login Accounts */
  async reLoginAccountsApiAccountsReLoginPost() {
    const path = `/api/accounts/re-login`;
    return this.request('POST', path, { body });
  }

  /** Get Relogin Progress */
  async getReloginProgressApiAccountsReLoginProgressProgressIdGet(progress_id) {
    const path = `/api/accounts/re-login/progress/${progress_id}`;
    return this.request('GET', path);
  }

  /** Recover Abnormal Accounts */
  async recoverAbnormalAccountsApiAccountsRecoverPost() {
    const path = `/api/accounts/recover`;
    return this.request('POST', path, { body });
  }

  /** Evict Stale Accounts */
  async evictStaleAccountsApiAccountsEvictStalePost() {
    const path = `/api/accounts/evict_stale`;
    return this.request('POST', path);
  }

  /** Export Accounts */
  async exportAccountsApiAccountsExportPost() {
    const path = `/api/accounts/export`;
    return this.request('POST', path, { body });
  }

  /** Batch Accounts */
  async batchAccountsApiAccountsBatchPost() {
    const path = `/api/accounts/batch`;
    return this.request('POST', path, { body });
  }

  /** Get Account Groups */
  async getAccountGroupsApiAccountsGroupsPost() {
    const path = `/api/accounts/groups`;
    return this.request('POST', path, { body });
  }

  /** Update Account */
  async updateAccountApiAccountsUpdatePost() {
    const path = `/api/accounts/update`;
    return this.request('POST', path, { body });
  }

  /** Start Oauth Login */
  async startOauthLoginApiAccountsOauthStartPost() {
    const path = `/api/accounts/oauth/start`;
    return this.request('POST', path, { body });
  }

  /** Finish Oauth Login */
  async finishOauthLoginApiAccountsOauthFinishPost() {
    const path = `/api/accounts/oauth/finish`;
    return this.request('POST', path, { body });
  }

  /** Get Account Health Scores */
  async getAccountHealthScoresApiAccountsHealthScoresGet() {
    const path = `/api/accounts/health-scores`;
    return this.request('GET', path);
  }

  /** List Cpa Pools */
  async listCpaPoolsApiCpaPoolsGet() {
    const path = `/api/cpa/pools`;
    return this.request('GET', path);
  }

  /** Create Cpa Pool */
  async createCpaPoolApiCpaPoolsPost() {
    const path = `/api/cpa/pools`;
    return this.request('POST', path, { body });
  }

  /** Update Cpa Pool */
  async updateCpaPoolApiCpaPoolsPoolIdPost(pool_id) {
    const path = `/api/cpa/pools/${pool_id}`;
    return this.request('POST', path, { body });
  }

  /** Delete Cpa Pool */
  async deleteCpaPoolApiCpaPoolsPoolIdDelete(pool_id) {
    const path = `/api/cpa/pools/${pool_id}`;
    return this.request('DELETE', path);
  }

  /** Cpa Pool Files */
  async cpaPoolFilesApiCpaPoolsPoolIdFilesGet(pool_id) {
    const path = `/api/cpa/pools/${pool_id}/files`;
    return this.request('GET', path);
  }

  /** Cpa Pool Import Progress */
  async cpaPoolImportProgressApiCpaPoolsPoolIdImportGet(pool_id) {
    const path = `/api/cpa/pools/${pool_id}/import`;
    return this.request('GET', path);
  }

  /** Cpa Pool Import */
  async cpaPoolImportApiCpaPoolsPoolIdImportPost(pool_id) {
    const path = `/api/cpa/pools/${pool_id}/import`;
    return this.request('POST', path, { body });
  }

  /** List Sub2Api Servers */
  async listSub2apiServersApiSub2apiServersGet() {
    const path = `/api/sub2api/servers`;
    return this.request('GET', path);
  }

  /** Create Sub2Api Server */
  async createSub2apiServerApiSub2apiServersPost() {
    const path = `/api/sub2api/servers`;
    return this.request('POST', path, { body });
  }

  /** Update Sub2Api Server */
  async updateSub2apiServerApiSub2apiServersServerIdPost(server_id) {
    const path = `/api/sub2api/servers/${server_id}`;
    return this.request('POST', path, { body });
  }

  /** Delete Sub2Api Server */
  async deleteSub2apiServerApiSub2apiServersServerIdDelete(server_id) {
    const path = `/api/sub2api/servers/${server_id}`;
    return this.request('DELETE', path);
  }

  /** Sub2Api Server Groups */
  async sub2apiServerGroupsApiSub2apiServersServerIdGroupsGet(server_id) {
    const path = `/api/sub2api/servers/${server_id}/groups`;
    return this.request('GET', path);
  }

  /** Sub2Api Server Accounts */
  async sub2apiServerAccountsApiSub2apiServersServerIdAccountsGet(server_id) {
    const path = `/api/sub2api/servers/${server_id}/accounts`;
    return this.request('GET', path);
  }

  /** Sub2Api Server Import Progress */
  async sub2apiServerImportProgressApiSub2apiServersServerIdImportGet(server_id) {
    const path = `/api/sub2api/servers/${server_id}/import`;
    return this.request('GET', path);
  }

  /** Sub2Api Server Import */
  async sub2apiServerImportApiSub2apiServersServerIdImportPost(server_id) {
    const path = `/api/sub2api/servers/${server_id}/import`;
    return this.request('POST', path, { body });
  }

  // --- Auth Keys ---

  /** List Keys */
  async listKeysApiAuthKeysGet() {
    const path = `/api/auth/keys`;
    return this.request('GET', path);
  }

  /** Create Key */
  async createKeyApiAuthKeysPost() {
    const path = `/api/auth/keys`;
    return this.request('POST', path, { body });
  }

  /** Update Key */
  async updateKeyApiAuthKeysKeyIdPost(key_id) {
    const path = `/api/auth/keys/${key_id}`;
    return this.request('POST', path, { body });
  }

  /** Delete Key */
  async deleteKeyApiAuthKeysKeyIdDelete(key_id) {
    const path = `/api/auth/keys/${key_id}`;
    return this.request('DELETE', path);
  }

  /** Revoke Key */
  async revokeKeyApiAuthKeysKeyIdRevokePost(key_id) {
    const path = `/api/auth/keys/${key_id}/revoke`;
    return this.request('POST', path);
  }

  /** Get Key Usage */
  async getKeyUsageApiAuthKeysUsageGet() {
    const path = `/api/auth/keys/usage`;
    const params = { key_id };
    return this.request('GET', path, { params: params });
  }

  // --- Dashboard ---

  /** Scheduler Dashboard */
  async schedulerDashboardApiDashboardSchedulerGet() {
    const path = `/api/dashboard/scheduler`;
    const params = { refresh };
    return this.request('GET', path, { params: params });
  }

  /** Circuit Breakers */
  async circuitBreakersApiDashboardCircuitBreakersGet() {
    const path = `/api/dashboard/circuit_breakers`;
    return this.request('GET', path);
  }

  /** Ops Overview */
  async opsOverviewApiDashboardOpsGet() {
    const path = `/api/dashboard/ops`;
    const params = { refresh };
    return this.request('GET', path, { params: params });
  }

  /** Usage Stats */
  async usageStatsApiDashboardUsageGet() {
    const path = `/api/dashboard/usage`;
    const params = { hours };
    return this.request('GET', path, { params: params });
  }

  /** Usage Totals */
  async usageTotalsApiDashboardUsageTotalsGet() {
    const path = `/api/dashboard/usage-totals`;
    return this.request('GET', path);
  }

  /** Usage Forecast Stats */
  async usageForecastStatsApiDashboardUsageForecastGet() {
    const path = `/api/dashboard/usage-forecast`;
    return this.request('GET', path);
  }

  /** Quota Detail */
  async quotaDetailApiDashboardQuotaGet() {
    const path = `/api/dashboard/quota`;
    return this.request('GET', path);
  }

  /** Capacity Stats */
  async capacityStatsApiDashboardCapacityGet() {
    const path = `/api/dashboard/capacity`;
    const params = { days };
    return this.request('GET', path, { params: params });
  }

  /** Cost Overview */
  async costOverviewApiDashboardCostGet() {
    const path = `/api/dashboard/cost`;
    return this.request('GET', path);
  }

  /** Latency Stats */
  async latencyStatsApiDashboardLatencyGet() {
    const path = `/api/dashboard/latency`;
    return this.request('GET', path);
  }

  /** Metrics Summary */
  async metricsSummaryApiDashboardMetricsSummaryGet() {
    const path = `/api/dashboard/metrics_summary`;
    return this.request('GET', path);
  }

  /** Adaptive Scheduler Status */
  async adaptiveSchedulerStatusApiDashboardAdaptiveSchedulerGet() {
    const path = `/api/dashboard/adaptive_scheduler`;
    return this.request('GET', path);
  }

  // --- Image Tasks ---

  /** List Image Tasks */
  async listImageTasksApiImageTasksGet() {
    const path = `/api/image-tasks`;
    const params = { ids };
    return this.request('GET', path, { params: params });
  }

  /** Create Generation Task */
  async createGenerationTaskApiImageTasksGenerationsPost() {
    const path = `/api/image-tasks/generations`;
    return this.request('POST', path, { body });
  }

  /** Create Edit Task */
  async createEditTaskApiImageTasksEditsPost() {
    const path = `/api/image-tasks/edits`;
    return this.request('POST', path);
  }

  /** Resume Image Poll */
  async resumeImagePollApiImageTasksTaskIdResumePollPost(task_id) {
    const path = `/api/image-tasks/${task_id}/resume-poll`;
    return this.request('POST', path, { body });
  }

  // --- Kookeey ---

  /** Get Kookeey Config */
  async getKookeeyConfigApiKookeeyConfigGet() {
    const path = `/api/kookeey/config`;
    return this.request('GET', path);
  }

  /** Update Kookeey Config */
  async updateKookeeyConfigApiKookeeyConfigPost() {
    const path = `/api/kookeey/config`;
    return this.request('POST', path, { body });
  }

  /** Get Kookeey Stats */
  async getKookeeyStatsApiKookeeyStatsGet() {
    const path = `/api/kookeey/stats`;
    return this.request('GET', path);
  }

  /** Test Kookeey */
  async testKookeeyApiKookeeyTestPost() {
    const path = `/api/kookeey/test`;
    return this.request('POST', path);
  }

  /** Extract Kookeey */
  async extractKookeeyApiKookeeyExtractPost() {
    const path = `/api/kookeey/extract`;
    return this.request('POST', path, { body });
  }

  /** Get Kookeey Traffic */
  async getKookeeyTrafficApiKookeeyTrafficGet() {
    const path = `/api/kookeey/traffic`;
    return this.request('GET', path);
  }

  /** Get Kookeey Balance */
  async getKookeeyBalanceApiKookeeyBalanceGet() {
    const path = `/api/kookeey/balance`;
    return this.request('GET', path);
  }

  /** Get Kookeey Traffic Detail */
  async getKookeeyTrafficDetailApiKookeeyTrafficDetailGet() {
    const path = `/api/kookeey/traffic-detail`;
    const params = { sdate, edate, gb };
    return this.request('GET', path, { params: params });
  }

  /** Get Kookeey Ip Usage */
  async getKookeeyIpUsageApiKookeeyIpUsageGet() {
    const path = `/api/kookeey/ip-usage`;
    return this.request('GET', path);
  }

  /** Probe Kookeey Ips */
  async probeKookeeyIpsApiKookeeyProbeIpsPost() {
    const path = `/api/kookeey/probe-ips`;
    return this.request('POST', path);
  }

  // --- Providers ---

  /** Get Providers */
  async getProvidersApiProvidersGet() {
    const path = `/api/providers`;
    const params = { refresh };
    return this.request('GET', path, { params: params });
  }

  // --- Proxy Pool ---

  /** List Proxies */
  async listProxiesApiProxiesGet() {
    const path = `/api/proxies`;
    return this.request('GET', path);
  }

  /** Add Proxy */
  async addProxyApiProxiesPost() {
    const path = `/api/proxies`;
    return this.request('POST', path, { body });
  }

  /** Batch Import Proxies */
  async batchImportProxiesApiProxiesBatchImportPost() {
    const path = `/api/proxies/batch-import`;
    return this.request('POST', path, { body });
  }

  /** Remove Proxy */
  async removeProxyApiProxiesUrlDelete(url) {
    const path = `/api/proxies/${url}`;
    return this.request('DELETE', path);
  }

  /** Update Weight */
  async updateWeightApiProxiesWeightPost() {
    const path = `/api/proxies/weight`;
    return this.request('POST', path, { body });
  }

  /** Set Strategy */
  async setStrategyApiProxiesStrategyPost() {
    const path = `/api/proxies/strategy`;
    return this.request('POST', path, { body });
  }

  /** Trigger Health Check */
  async triggerHealthCheckApiProxiesHealthCheckPost() {
    const path = `/api/proxies/health-check`;
    return this.request('POST', path);
  }

  /** Probe Kookeey Egress */
  async probeKookeeyEgressApiProxiesKookeeyEgressPost() {
    const path = `/api/proxies/kookeey-egress`;
    return this.request('POST', path, { body });
  }

  /** Probe Egress Ip */
  async probeEgressIpApiProxiesProbeIpPost() {
    const path = `/api/proxies/probe-ip`;
    return this.request('POST', path, { body });
  }

  /** Get Egress Ip */
  async getEgressIpApiProxiesEgressIpGet() {
    const path = `/api/proxies/egress-ip`;
    return this.request('GET', path);
  }

  // --- System ---

  /** Login */
  async loginAuthLoginPost() {
    const path = `/auth/login`;
    return this.request('POST', path);
  }

  /** Get Version */
  async getVersionVersionGet() {
    const path = `/version`;
    return this.request('GET', path);
  }

  /** Health Ready */
  async healthReadyApiSystemHealthReadyGet() {
    const path = `/api/system/health/ready`;
    return this.request('GET', path);
  }

  /** Get Settings */
  async getSettingsApiSettingsGet() {
    const path = `/api/settings`;
    return this.request('GET', path);
  }

  /** Save Settings */
  async saveSettingsApiSettingsPost() {
    const path = `/api/settings`;
    return this.request('POST', path, { body });
  }

  /** Get Images */
  async getImagesApiImagesGet() {
    const path = `/api/images`;
    const params = { start_date, end_date };
    return this.request('GET', path, { params: params });
  }

  /** Delete Images Endpoint */
  async deleteImagesEndpointApiImagesDeletePost() {
    const path = `/api/images/delete`;
    return this.request('POST', path, { body });
  }

  /** Download Images Endpoint */
  async downloadImagesEndpointApiImagesDownloadPost() {
    const path = `/api/images/download`;
    return this.request('POST', path, { body });
  }

  /** Download Single Image Endpoint */
  async downloadSingleImageEndpointApiImagesDownloadImagePathGet(image_path) {
    const path = `/api/images/download/${image_path}`;
    return this.request('GET', path);
  }

  /** Proxy Download Image Endpoint */
  async proxyDownloadImageEndpointApiImagesProxyDownloadGet() {
    const path = `/api/images/proxy-download`;
    const params = { url };
    return this.request('GET', path, { params: params });
  }

  /** Get Logs */
  async getLogsApiLogsGet() {
    const path = `/api/logs`;
    const params = { type, start_date, end_date, account_email, days, event, request_id, result, page, page_size };
    return this.request('GET', path, { params: params });
  }

  /** Delete Logs */
  async deleteLogsApiLogsDeletePost() {
    const path = `/api/logs/delete`;
    return this.request('POST', path, { body });
  }

  /** Get Log Level */
  async getLogLevelApiSystemLogLevelGet() {
    const path = `/api/system/log-level`;
    return this.request('GET', path);
  }

  /** Set Log Level */
  async setLogLevelApiSystemLogLevelPost() {
    const path = `/api/system/log-level`;
    return this.request('POST', path, { body });
  }

  /** Get Audit */
  async getAuditApiAuditGet() {
    const path = `/api/audit`;
    const params = { days, limit, result, operator, action, start_date, end_date, page, page_size };
    return this.request('GET', path, { params: params });
  }

  /** Export Audit Csv */
  async exportAuditCsvApiAuditExportGet() {
    const path = `/api/audit/export`;
    const params = { days, result, operator, action, start_date, end_date };
    return this.request('GET', path, { params: params });
  }

  /** Test Proxy Endpoint */
  async testProxyEndpointApiProxyTestPost() {
    const path = `/api/proxy/test`;
    return this.request('POST', path, { body });
  }

  /** Get Proxy Runtime Endpoint */
  async getProxyRuntimeEndpointApiProxyRuntimeGet() {
    const path = `/api/proxy/runtime`;
    return this.request('GET', path);
  }

  /** Save Proxy Runtime Endpoint */
  async saveProxyRuntimeEndpointApiProxyRuntimePost() {
    const path = `/api/proxy/runtime`;
    return this.request('POST', path, { body });
  }

  /** Test Proxy Clearance Endpoint */
  async testProxyClearanceEndpointApiProxyClearanceTestPost() {
    const path = `/api/proxy/clearance/test`;
    return this.request('POST', path, { body });
  }

  /** Get Storage Info */
  async getStorageInfoApiStorageInfoGet() {
    const path = `/api/storage/info`;
    return this.request('GET', path);
  }

  /** Test Backup Connection */
  async testBackupConnectionApiBackupTestPost() {
    const path = `/api/backup/test`;
    return this.request('POST', path);
  }

  /** Test Image Storage Endpoint */
  async testImageStorageEndpointApiImageStorageTestPost() {
    const path = `/api/image-storage/test`;
    return this.request('POST', path);
  }

  /** Sync Image Storage Endpoint */
  async syncImageStorageEndpointApiImageStorageSyncPost() {
    const path = `/api/image-storage/sync`;
    return this.request('POST', path);
  }

  /** Get Backups */
  async getBackupsApiBackupsGet() {
    const path = `/api/backups`;
    return this.request('GET', path);
  }

  /** Run Backup Endpoint */
  async runBackupEndpointApiBackupsRunPost() {
    const path = `/api/backups/run`;
    return this.request('POST', path);
  }

  /** Delete Backup Endpoint */
  async deleteBackupEndpointApiBackupsDeletePost() {
    const path = `/api/backups/delete`;
    return this.request('POST', path, { body });
  }

  /** Get Backup Detail */
  async getBackupDetailApiBackupsDetailGet() {
    const path = `/api/backups/detail`;
    const params = { key };
    return this.request('GET', path, { params: params });
  }

  /** Download Backup Endpoint */
  async downloadBackupEndpointApiBackupsDownloadGet() {
    const path = `/api/backups/download`;
    const params = { key };
    return this.request('GET', path, { params: params });
  }

  /** List Image Tags */
  async listImageTagsApiImagesTagsGet() {
    const path = `/api/images/tags`;
    return this.request('GET', path);
  }

  /** Update Image Tags */
  async updateImageTagsApiImagesTagsPost() {
    const path = `/api/images/tags`;
    return this.request('POST', path, { body });
  }

  /** Delete Image Tag */
  async deleteImageTagApiImagesTagsTagDelete(tag) {
    const path = `/api/images/tags/${tag}`;
    return this.request('DELETE', path);
  }

  /** Get Image Storage */
  async getImageStorageApiImagesStorageGet() {
    const path = `/api/images/storage`;
    return this.request('GET', path);
  }

  /** Compress All Images */
  async compressAllImagesApiImagesStorageCompressPost() {
    const path = `/api/images/storage/compress`;
    return this.request('POST', path);
  }

  /** Cleanup To Target */
  async cleanupToTargetApiImagesStorageCleanupToTargetPost() {
    const path = `/api/images/storage/cleanup-to-target`;
    const params = { target_free_mb, dry_run };
    return this.request('POST', path, { params: params });
  }

  /** Get Last Diagnose */
  async getLastDiagnoseApiSystemDiagnoseGet() {
    const path = `/api/system/diagnose`;
    return this.request('GET', path);
  }

  /** Run Diagnose */
  async runDiagnoseApiSystemDiagnosePost() {
    const path = `/api/system/diagnose`;
    return this.request('POST', path);
  }

  /** Get Healing History */
  async getHealingHistoryApiSystemHealingHistoryGet() {
    const path = `/api/system/healing/history`;
    const params = { limit };
    return this.request('GET', path, { params: params });
  }

  /** Run Healing */
  async runHealingApiSystemHealingRunPost() {
    const path = `/api/system/healing/run`;
    return this.request('POST', path);
  }

  /** Clear Healing History */
  async clearHealingHistoryApiSystemHealingClearHistoryPost() {
    const path = `/api/system/healing/clear-history`;
    return this.request('POST', path);
  }

  /** Health Dashboard */
  async healthDashboardHealthGet() {
    const path = `/health`;
    const params = { format };
    return this.request('GET', path, { params: params });
  }

  // --- logs ---

  /** Aggregate Logs */
  async aggregateLogsApiLogsAggregateGet() {
    const path = `/api/logs/aggregate`;
    const params = { group_by, start_date, end_date, period };
    return this.request('GET', path, { params: params });
  }

  /** Export Logs */
  async exportLogsApiLogsExportGet() {
    const path = `/api/logs/export`;
    const params = { format, page, page_size, fields, type, start_date, end_date };
    return this.request('GET', path, { params: params });
  }

  /** Slow Queries */
  async slowQueriesApiLogsSlowQueriesGet() {
    const path = `/api/logs/slow-queries`;
    const params = { start_date, end_date, threshold_ms };
    return this.request('GET', path, { params: params });
  }

  // --- tracing ---

  /** Get Traces */
  async getTracesApiTracingTracesGet() {
    const path = `/api/tracing/traces`;
    const params = { limit, slow_only };
    return this.request('GET', path, { params: params });
  }

  /** Get Tracing Stats */
  async getTracingStatsApiTracingStatsGet() {
    const path = `/api/tracing/stats`;
    return this.request('GET', path);
  }

}

export default Chatgpt2apiClient;