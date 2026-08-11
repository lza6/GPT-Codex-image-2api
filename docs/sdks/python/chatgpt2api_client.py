"""
chatgpt2api SDK — 自动生成 (v2.24.0)

用法：
    client = Chatgpt2apiClient(base_url='/', api_key='your-key')
    models = client.list_models()
"""
from __future__ import annotations

import json
from typing import Any

import httpx


VERSION = "2.24.0"


class Chatgpt2apiClient:
    """chatgpt2api API 客户端"""

    def __init__(
        self,
        base_url: str = "/",
        api_key: str | None = None,
        timeout: float = 60.0,
    ):
        self.base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = httpx.Client(timeout=timeout, headers=self._headers)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Chatgpt2apiClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # --- 数据模型 ---

    class AccountBatchRequest:
        def __init__(self, **kwargs: Any):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class AccountCreateRequest:
        def __init__(self, **kwargs: Any):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class AccountDeleteRequest:
        def __init__(self, **kwargs: Any):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class AccountExportRequest:
        def __init__(self, **kwargs: Any):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class AccountGroupRenameRequest:
        def __init__(self, **kwargs: Any):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class AccountRefreshRequest:
        def __init__(self, **kwargs: Any):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class AccountUpdateRequest:
        def __init__(self, **kwargs: Any):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class AnthropicMessageRequest:
        def __init__(self, **kwargs: Any):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class BackupDeleteRequest:
        def __init__(self, **kwargs: Any):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class CPAImportRequest:
        def __init__(self, **kwargs: Any):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class CPAPoolCreateRequest:
        def __init__(self, **kwargs: Any):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class CPAPoolUpdateRequest:
        def __init__(self, **kwargs: Any):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class ChatCompletionRequest:
        def __init__(self, **kwargs: Any):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class ClearanceTestRequest:
        def __init__(self, **kwargs: Any):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class EditableFileTaskRequest:
        def __init__(self, **kwargs: Any):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class HTTPValidationError:
        def __init__(self, **kwargs: Any):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class ImageDeleteRequest:
        def __init__(self, **kwargs: Any):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class ImageDownloadRequest:
        def __init__(self, **kwargs: Any):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class ImageGenerationRequest:
        def __init__(self, **kwargs: Any):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class ImageGenerationTaskRequest:
        def __init__(self, **kwargs: Any):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class ImageTagsRequest:
        def __init__(self, **kwargs: Any):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class KeyCreateRequest:
        def __init__(self, **kwargs: Any):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class KeyUpdateRequest:
        def __init__(self, **kwargs: Any):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class KookeeyConfigRequest:
        def __init__(self, **kwargs: Any):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class KookeeyExtractRequest:
        def __init__(self, **kwargs: Any):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class LogDeleteRequest:
        def __init__(self, **kwargs: Any):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class LogLevelRequest:
        def __init__(self, **kwargs: Any):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class OAuthLoginFinishRequest:
        def __init__(self, **kwargs: Any):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class OAuthLoginStartRequest:
        def __init__(self, **kwargs: Any):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class ProxyAddRequest:
        def __init__(self, **kwargs: Any):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class ProxyBatchImportRequest:
        def __init__(self, **kwargs: Any):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class ProxyStrategyRequest:
        def __init__(self, **kwargs: Any):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class ProxyTestRequest:
        def __init__(self, **kwargs: Any):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class ProxyWeightRequest:
        def __init__(self, **kwargs: Any):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class ResponseCreateRequest:
        def __init__(self, **kwargs: Any):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class ResumePollRequest:
        def __init__(self, **kwargs: Any):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class SearchRequest:
        def __init__(self, **kwargs: Any):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class SettingsUpdateRequest:
        pass

    class Sub2APIImportRequest:
        def __init__(self, **kwargs: Any):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class Sub2APIServerCreateRequest:
        def __init__(self, **kwargs: Any):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class Sub2APIServerUpdateRequest:
        def __init__(self, **kwargs: Any):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class UserKeyCreateRequest:
        def __init__(self, **kwargs: Any):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class UserKeyUpdateRequest:
        def __init__(self, **kwargs: Any):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class ValidationError:
        def __init__(self, **kwargs: Any):
            for k, v in kwargs.items():
                setattr(self, k, v)

    # --- API 方法 ---

    # --- AI ---

    def list_models_v1_models_get(self):
        """List Models"""
        url = self.base_url + "/v1/models"
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    def generate_images_v1_images_generations_post(self, body: dict | None = None):
        """Generate Images"""
        url = self.base_url + "/v1/images/generations"
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    def edit_images_v1_images_edits_post(self):
        """Edit Images"""
        url = self.base_url + "/v1/images/edits"
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    def create_chat_completion_v1_chat_completions_post(self, body: dict | None = None):
        """Create Chat Completion"""
        url = self.base_url + "/v1/chat/completions"
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    def create_response_v1_responses_post(self, body: dict | None = None):
        """Create Response"""
        url = self.base_url + "/v1/responses"
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    def create_message_v1_messages_post(self, body: dict | None = None):
        """Create Message"""
        url = self.base_url + "/v1/messages"
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    def search_v1_search_post(self, body: dict | None = None):
        """Search"""
        url = self.base_url + "/v1/search"
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    def list_editable_file_tasks_v1_editable_file_tasks_get(self, ids: Any = None):
        """List Editable File Tasks"""
        url = self.base_url + "/v1/editable-file-tasks"
        params = {k: v for k, v in locals().items() if k in ['ids'] and v is not None}
        if params:
            from urllib.parse import urlencode
            url += '?' + urlencode(params)
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    def download_editable_file_files__file_path__get(self, file_path: str):
        """Download Editable File"""
        url = self.base_url + "/files/{file_path}"
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    def create_ppt_task_v1_ppt_generations_post(self, body: dict | None = None):
        """Create Ppt Task"""
        url = self.base_url + "/v1/ppt/generations"
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    def create_psd_task_v1_psd_generations_post(self, body: dict | None = None):
        """Create Psd Task"""
        url = self.base_url + "/v1/psd/generations"
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    # --- Accounts ---

    def list_user_keys_api_auth_users_get(self):
        """List User Keys"""
        url = self.base_url + "/api/auth/users"
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    def create_user_key_api_auth_users_post(self, body: dict | None = None):
        """Create User Key"""
        url = self.base_url + "/api/auth/users"
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    def update_user_key_api_auth_users__key_id__post(self, key_id: str, body: dict | None = None):
        """Update User Key"""
        url = self.base_url + "/api/auth/users/{key_id}"
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    def delete_user_key_api_auth_users__key_id__delete(self, key_id: str):
        """Delete User Key"""
        url = self.base_url + "/api/auth/users/{key_id}"
        resp = self._client.delete(url)
        resp.raise_for_status()
        return resp.json()

    def get_accounts_api_accounts_get(self, page: Any = None, page_size: Any = None, provider: Any = None):
        """Get Accounts"""
        url = self.base_url + "/api/accounts"
        params = {k: v for k, v in locals().items() if k in ['page', 'page_size', 'provider'] and v is not None}
        if params:
            from urllib.parse import urlencode
            url += '?' + urlencode(params)
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    def create_accounts_api_accounts_post(self, body: dict | None = None):
        """Create Accounts"""
        url = self.base_url + "/api/accounts"
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    def delete_accounts_api_accounts_delete(self, body: dict | None = None):
        """Delete Accounts"""
        url = self.base_url + "/api/accounts"
        resp = self._client.delete(url)
        resp.raise_for_status()
        return resp.json()

    def refresh_accounts_api_accounts_refresh_post(self, body: dict | None = None):
        """Refresh Accounts"""
        url = self.base_url + "/api/accounts/refresh"
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    def get_refresh_progress_api_accounts_refresh_progress__progress_id__get(self, progress_id: str):
        """Get Refresh Progress"""
        url = self.base_url + "/api/accounts/refresh/progress/{progress_id}"
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    def re_login_accounts_api_accounts_re_login_post(self, body: dict | None = None):
        """Re Login Accounts"""
        url = self.base_url + "/api/accounts/re-login"
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    def get_relogin_progress_api_accounts_re_login_progress__progress_id__get(self, progress_id: str):
        """Get Relogin Progress"""
        url = self.base_url + "/api/accounts/re-login/progress/{progress_id}"
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    def recover_abnormal_accounts_api_accounts_recover_post(self, body: dict | None = None):
        """Recover Abnormal Accounts"""
        url = self.base_url + "/api/accounts/recover"
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    def evict_stale_accounts_api_accounts_evict_stale_post(self):
        """Evict Stale Accounts"""
        url = self.base_url + "/api/accounts/evict_stale"
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    def export_accounts_api_accounts_export_post(self, body: dict | None = None):
        """Export Accounts"""
        url = self.base_url + "/api/accounts/export"
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    def batch_accounts_api_accounts_batch_post(self, body: dict | None = None):
        """Batch Accounts"""
        url = self.base_url + "/api/accounts/batch"
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    def get_account_groups_api_accounts_groups_post(self, body: dict | None = None):
        """Get Account Groups"""
        url = self.base_url + "/api/accounts/groups"
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    def update_account_api_accounts_update_post(self, body: dict | None = None):
        """Update Account"""
        url = self.base_url + "/api/accounts/update"
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    def start_oauth_login_api_accounts_oauth_start_post(self, body: dict | None = None):
        """Start Oauth Login"""
        url = self.base_url + "/api/accounts/oauth/start"
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    def finish_oauth_login_api_accounts_oauth_finish_post(self, body: dict | None = None):
        """Finish Oauth Login"""
        url = self.base_url + "/api/accounts/oauth/finish"
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    def get_account_health_scores_api_accounts_health_scores_get(self):
        """Get Account Health Scores"""
        url = self.base_url + "/api/accounts/health-scores"
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    def list_cpa_pools_api_cpa_pools_get(self):
        """List Cpa Pools"""
        url = self.base_url + "/api/cpa/pools"
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    def create_cpa_pool_api_cpa_pools_post(self, body: dict | None = None):
        """Create Cpa Pool"""
        url = self.base_url + "/api/cpa/pools"
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    def update_cpa_pool_api_cpa_pools__pool_id__post(self, pool_id: str, body: dict | None = None):
        """Update Cpa Pool"""
        url = self.base_url + "/api/cpa/pools/{pool_id}"
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    def delete_cpa_pool_api_cpa_pools__pool_id__delete(self, pool_id: str):
        """Delete Cpa Pool"""
        url = self.base_url + "/api/cpa/pools/{pool_id}"
        resp = self._client.delete(url)
        resp.raise_for_status()
        return resp.json()

    def cpa_pool_files_api_cpa_pools__pool_id__files_get(self, pool_id: str):
        """Cpa Pool Files"""
        url = self.base_url + "/api/cpa/pools/{pool_id}/files"
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    def cpa_pool_import_progress_api_cpa_pools__pool_id__import_get(self, pool_id: str):
        """Cpa Pool Import Progress"""
        url = self.base_url + "/api/cpa/pools/{pool_id}/import"
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    def cpa_pool_import_api_cpa_pools__pool_id__import_post(self, pool_id: str, body: dict | None = None):
        """Cpa Pool Import"""
        url = self.base_url + "/api/cpa/pools/{pool_id}/import"
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    def list_sub2api_servers_api_sub2api_servers_get(self):
        """List Sub2Api Servers"""
        url = self.base_url + "/api/sub2api/servers"
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    def create_sub2api_server_api_sub2api_servers_post(self, body: dict | None = None):
        """Create Sub2Api Server"""
        url = self.base_url + "/api/sub2api/servers"
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    def update_sub2api_server_api_sub2api_servers__server_id__post(self, server_id: str, body: dict | None = None):
        """Update Sub2Api Server"""
        url = self.base_url + "/api/sub2api/servers/{server_id}"
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    def delete_sub2api_server_api_sub2api_servers__server_id__delete(self, server_id: str):
        """Delete Sub2Api Server"""
        url = self.base_url + "/api/sub2api/servers/{server_id}"
        resp = self._client.delete(url)
        resp.raise_for_status()
        return resp.json()

    def sub2api_server_groups_api_sub2api_servers__server_id__groups_get(self, server_id: str):
        """Sub2Api Server Groups"""
        url = self.base_url + "/api/sub2api/servers/{server_id}/groups"
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    def sub2api_server_accounts_api_sub2api_servers__server_id__accounts_get(self, server_id: str):
        """Sub2Api Server Accounts"""
        url = self.base_url + "/api/sub2api/servers/{server_id}/accounts"
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    def sub2api_server_import_progress_api_sub2api_servers__server_id__import_get(self, server_id: str):
        """Sub2Api Server Import Progress"""
        url = self.base_url + "/api/sub2api/servers/{server_id}/import"
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    def sub2api_server_import_api_sub2api_servers__server_id__import_post(self, server_id: str, body: dict | None = None):
        """Sub2Api Server Import"""
        url = self.base_url + "/api/sub2api/servers/{server_id}/import"
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    # --- Auth Keys ---

    def list_keys_api_auth_keys_get(self):
        """List Keys"""
        url = self.base_url + "/api/auth/keys"
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    def create_key_api_auth_keys_post(self, body: dict | None = None):
        """Create Key"""
        url = self.base_url + "/api/auth/keys"
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    def update_key_api_auth_keys__key_id__post(self, key_id: str, body: dict | None = None):
        """Update Key"""
        url = self.base_url + "/api/auth/keys/{key_id}"
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    def delete_key_api_auth_keys__key_id__delete(self, key_id: str):
        """Delete Key"""
        url = self.base_url + "/api/auth/keys/{key_id}"
        resp = self._client.delete(url)
        resp.raise_for_status()
        return resp.json()

    def revoke_key_api_auth_keys__key_id__revoke_post(self, key_id: str):
        """Revoke Key"""
        url = self.base_url + "/api/auth/keys/{key_id}/revoke"
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    def get_key_usage_api_auth_keys_usage_get(self, key_id: Any = None):
        """Get Key Usage"""
        url = self.base_url + "/api/auth/keys/usage"
        params = {k: v for k, v in locals().items() if k in ['key_id'] and v is not None}
        if params:
            from urllib.parse import urlencode
            url += '?' + urlencode(params)
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    # --- Dashboard ---

    def scheduler_dashboard_api_dashboard_scheduler_get(self):
        """Scheduler Dashboard"""
        url = self.base_url + "/api/dashboard/scheduler"
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    def circuit_breakers_api_dashboard_circuit_breakers_get(self):
        """Circuit Breakers"""
        url = self.base_url + "/api/dashboard/circuit_breakers"
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    def ops_overview_api_dashboard_ops_get(self):
        """Ops Overview"""
        url = self.base_url + "/api/dashboard/ops"
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    def usage_stats_api_dashboard_usage_get(self, hours: Any = None):
        """Usage Stats"""
        url = self.base_url + "/api/dashboard/usage"
        params = {k: v for k, v in locals().items() if k in ['hours'] and v is not None}
        if params:
            from urllib.parse import urlencode
            url += '?' + urlencode(params)
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    def usage_totals_api_dashboard_usage_totals_get(self):
        """Usage Totals"""
        url = self.base_url + "/api/dashboard/usage-totals"
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    def usage_forecast_stats_api_dashboard_usage_forecast_get(self):
        """Usage Forecast Stats"""
        url = self.base_url + "/api/dashboard/usage-forecast"
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    def quota_detail_api_dashboard_quota_get(self):
        """Quota Detail"""
        url = self.base_url + "/api/dashboard/quota"
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    def capacity_stats_api_dashboard_capacity_get(self, days: Any = None):
        """Capacity Stats"""
        url = self.base_url + "/api/dashboard/capacity"
        params = {k: v for k, v in locals().items() if k in ['days'] and v is not None}
        if params:
            from urllib.parse import urlencode
            url += '?' + urlencode(params)
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    def latency_stats_api_dashboard_latency_get(self):
        """Latency Stats"""
        url = self.base_url + "/api/dashboard/latency"
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    def metrics_summary_api_dashboard_metrics_summary_get(self):
        """Metrics Summary"""
        url = self.base_url + "/api/dashboard/metrics_summary"
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    def adaptive_scheduler_status_api_dashboard_adaptive_scheduler_get(self):
        """Adaptive Scheduler Status"""
        url = self.base_url + "/api/dashboard/adaptive_scheduler"
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    # --- Image Tasks ---

    def list_image_tasks_api_image_tasks_get(self, ids: Any = None):
        """List Image Tasks"""
        url = self.base_url + "/api/image-tasks"
        params = {k: v for k, v in locals().items() if k in ['ids'] and v is not None}
        if params:
            from urllib.parse import urlencode
            url += '?' + urlencode(params)
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    def create_generation_task_api_image_tasks_generations_post(self, body: dict | None = None):
        """Create Generation Task"""
        url = self.base_url + "/api/image-tasks/generations"
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    def create_edit_task_api_image_tasks_edits_post(self):
        """Create Edit Task"""
        url = self.base_url + "/api/image-tasks/edits"
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    def resume_image_poll_api_image_tasks__task_id__resume_poll_post(self, task_id: str, body: dict | None = None):
        """Resume Image Poll"""
        url = self.base_url + "/api/image-tasks/{task_id}/resume-poll"
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    # --- Kookeey ---

    def get_kookeey_config_api_kookeey_config_get(self):
        """Get Kookeey Config"""
        url = self.base_url + "/api/kookeey/config"
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    def update_kookeey_config_api_kookeey_config_post(self, body: dict | None = None):
        """Update Kookeey Config"""
        url = self.base_url + "/api/kookeey/config"
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    def get_kookeey_stats_api_kookeey_stats_get(self):
        """Get Kookeey Stats"""
        url = self.base_url + "/api/kookeey/stats"
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    def test_kookeey_api_kookeey_test_post(self):
        """Test Kookeey"""
        url = self.base_url + "/api/kookeey/test"
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    def extract_kookeey_api_kookeey_extract_post(self, body: dict | None = None):
        """Extract Kookeey"""
        url = self.base_url + "/api/kookeey/extract"
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    def get_kookeey_traffic_api_kookeey_traffic_get(self):
        """Get Kookeey Traffic"""
        url = self.base_url + "/api/kookeey/traffic"
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    def get_kookeey_balance_api_kookeey_balance_get(self):
        """Get Kookeey Balance"""
        url = self.base_url + "/api/kookeey/balance"
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    def get_kookeey_traffic_detail_api_kookeey_traffic_detail_get(self, sdate: Any = None, edate: Any = None, gb: Any = None):
        """Get Kookeey Traffic Detail"""
        url = self.base_url + "/api/kookeey/traffic-detail"
        params = {k: v for k, v in locals().items() if k in ['sdate', 'edate', 'gb'] and v is not None}
        if params:
            from urllib.parse import urlencode
            url += '?' + urlencode(params)
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    def get_kookeey_ip_usage_api_kookeey_ip_usage_get(self):
        """Get Kookeey Ip Usage"""
        url = self.base_url + "/api/kookeey/ip-usage"
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    def probe_kookeey_ips_api_kookeey_probe_ips_post(self):
        """Probe Kookeey Ips"""
        url = self.base_url + "/api/kookeey/probe-ips"
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    # --- Providers ---

    def get_providers_api_providers_get(self):
        """Get Providers"""
        url = self.base_url + "/api/providers"
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    # --- Proxy Pool ---

    def list_proxies_api_proxies_get(self):
        """List Proxies"""
        url = self.base_url + "/api/proxies"
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    def add_proxy_api_proxies_post(self, body: dict | None = None):
        """Add Proxy"""
        url = self.base_url + "/api/proxies"
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    def batch_import_proxies_api_proxies_batch_import_post(self, body: dict | None = None):
        """Batch Import Proxies"""
        url = self.base_url + "/api/proxies/batch-import"
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    def remove_proxy_api_proxies__url__delete(self, url: str):
        """Remove Proxy"""
        url = self.base_url + "/api/proxies/{url}"
        resp = self._client.delete(url)
        resp.raise_for_status()
        return resp.json()

    def update_weight_api_proxies_weight_post(self, body: dict | None = None):
        """Update Weight"""
        url = self.base_url + "/api/proxies/weight"
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    def set_strategy_api_proxies_strategy_post(self, body: dict | None = None):
        """Set Strategy"""
        url = self.base_url + "/api/proxies/strategy"
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    def trigger_health_check_api_proxies_health_check_post(self):
        """Trigger Health Check"""
        url = self.base_url + "/api/proxies/health-check"
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    def probe_kookeey_egress_api_proxies_kookeey_egress_post(self, body: dict | None = None):
        """Probe Kookeey Egress"""
        url = self.base_url + "/api/proxies/kookeey-egress"
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    def probe_egress_ip_api_proxies_probe_ip_post(self, body: dict | None = None):
        """Probe Egress Ip"""
        url = self.base_url + "/api/proxies/probe-ip"
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    def get_egress_ip_api_proxies_egress_ip_get(self):
        """Get Egress Ip"""
        url = self.base_url + "/api/proxies/egress-ip"
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    # --- System ---

    def login_auth_login_post(self):
        """Login"""
        url = self.base_url + "/auth/login"
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    def get_version_version_get(self):
        """Get Version"""
        url = self.base_url + "/version"
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    def health_ready_api_system_health_ready_get(self):
        """Health Ready"""
        url = self.base_url + "/api/system/health/ready"
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    def get_settings_api_settings_get(self):
        """Get Settings"""
        url = self.base_url + "/api/settings"
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    def save_settings_api_settings_post(self, body: dict | None = None):
        """Save Settings"""
        url = self.base_url + "/api/settings"
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    def get_images_api_images_get(self, start_date: Any = None, end_date: Any = None):
        """Get Images"""
        url = self.base_url + "/api/images"
        params = {k: v for k, v in locals().items() if k in ['start_date', 'end_date'] and v is not None}
        if params:
            from urllib.parse import urlencode
            url += '?' + urlencode(params)
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    def delete_images_endpoint_api_images_delete_post(self, body: dict | None = None):
        """Delete Images Endpoint"""
        url = self.base_url + "/api/images/delete"
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    def download_images_endpoint_api_images_download_post(self, body: dict | None = None):
        """Download Images Endpoint"""
        url = self.base_url + "/api/images/download"
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    def download_single_image_endpoint_api_images_download__image_path__get(self, image_path: str):
        """Download Single Image Endpoint"""
        url = self.base_url + "/api/images/download/{image_path}"
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    def proxy_download_image_endpoint_api_images_proxy_download_get(self, url: Any = None):
        """Proxy Download Image Endpoint"""
        url = self.base_url + "/api/images/proxy-download"
        params = {k: v for k, v in locals().items() if k in ['url'] and v is not None}
        if params:
            from urllib.parse import urlencode
            url += '?' + urlencode(params)
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    def get_logs_api_logs_get(self, type: Any = None, start_date: Any = None, end_date: Any = None, account_email: Any = None, days: Any = None, event: Any = None, request_id: Any = None, result: Any = None, page: Any = None, page_size: Any = None):
        """Get Logs"""
        url = self.base_url + "/api/logs"
        params = {k: v for k, v in locals().items() if k in ['type', 'start_date', 'end_date', 'account_email', 'days', 'event', 'request_id', 'result', 'page', 'page_size'] and v is not None}
        if params:
            from urllib.parse import urlencode
            url += '?' + urlencode(params)
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    def delete_logs_api_logs_delete_post(self, body: dict | None = None):
        """Delete Logs"""
        url = self.base_url + "/api/logs/delete"
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    def get_log_level_api_system_log_level_get(self):
        """Get Log Level"""
        url = self.base_url + "/api/system/log-level"
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    def set_log_level_api_system_log_level_post(self, body: dict | None = None):
        """Set Log Level"""
        url = self.base_url + "/api/system/log-level"
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    def get_audit_api_audit_get(self, days: Any = None, limit: Any = None, result: Any = None, operator: Any = None, action: Any = None, start_date: Any = None, end_date: Any = None, page: Any = None, page_size: Any = None):
        """Get Audit"""
        url = self.base_url + "/api/audit"
        params = {k: v for k, v in locals().items() if k in ['days', 'limit', 'result', 'operator', 'action', 'start_date', 'end_date', 'page', 'page_size'] and v is not None}
        if params:
            from urllib.parse import urlencode
            url += '?' + urlencode(params)
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    def export_audit_csv_api_audit_export_get(self, days: Any = None, result: Any = None, operator: Any = None, action: Any = None, start_date: Any = None, end_date: Any = None):
        """Export Audit Csv"""
        url = self.base_url + "/api/audit/export"
        params = {k: v for k, v in locals().items() if k in ['days', 'result', 'operator', 'action', 'start_date', 'end_date'] and v is not None}
        if params:
            from urllib.parse import urlencode
            url += '?' + urlencode(params)
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    def test_proxy_endpoint_api_proxy_test_post(self, body: dict | None = None):
        """Test Proxy Endpoint"""
        url = self.base_url + "/api/proxy/test"
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    def get_proxy_runtime_endpoint_api_proxy_runtime_get(self):
        """Get Proxy Runtime Endpoint"""
        url = self.base_url + "/api/proxy/runtime"
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    def save_proxy_runtime_endpoint_api_proxy_runtime_post(self, body: dict | None = None):
        """Save Proxy Runtime Endpoint"""
        url = self.base_url + "/api/proxy/runtime"
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    def test_proxy_clearance_endpoint_api_proxy_clearance_test_post(self, body: dict | None = None):
        """Test Proxy Clearance Endpoint"""
        url = self.base_url + "/api/proxy/clearance/test"
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    def get_storage_info_api_storage_info_get(self):
        """Get Storage Info"""
        url = self.base_url + "/api/storage/info"
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    def test_backup_connection_api_backup_test_post(self):
        """Test Backup Connection"""
        url = self.base_url + "/api/backup/test"
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    def test_image_storage_endpoint_api_image_storage_test_post(self):
        """Test Image Storage Endpoint"""
        url = self.base_url + "/api/image-storage/test"
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    def sync_image_storage_endpoint_api_image_storage_sync_post(self):
        """Sync Image Storage Endpoint"""
        url = self.base_url + "/api/image-storage/sync"
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    def get_backups_api_backups_get(self):
        """Get Backups"""
        url = self.base_url + "/api/backups"
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    def run_backup_endpoint_api_backups_run_post(self):
        """Run Backup Endpoint"""
        url = self.base_url + "/api/backups/run"
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    def delete_backup_endpoint_api_backups_delete_post(self, body: dict | None = None):
        """Delete Backup Endpoint"""
        url = self.base_url + "/api/backups/delete"
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    def get_backup_detail_api_backups_detail_get(self, key: Any = None):
        """Get Backup Detail"""
        url = self.base_url + "/api/backups/detail"
        params = {k: v for k, v in locals().items() if k in ['key'] and v is not None}
        if params:
            from urllib.parse import urlencode
            url += '?' + urlencode(params)
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    def download_backup_endpoint_api_backups_download_get(self, key: Any = None):
        """Download Backup Endpoint"""
        url = self.base_url + "/api/backups/download"
        params = {k: v for k, v in locals().items() if k in ['key'] and v is not None}
        if params:
            from urllib.parse import urlencode
            url += '?' + urlencode(params)
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    def list_image_tags_api_images_tags_get(self):
        """List Image Tags"""
        url = self.base_url + "/api/images/tags"
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    def update_image_tags_api_images_tags_post(self, body: dict | None = None):
        """Update Image Tags"""
        url = self.base_url + "/api/images/tags"
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    def delete_image_tag_api_images_tags__tag__delete(self, tag: str):
        """Delete Image Tag"""
        url = self.base_url + "/api/images/tags/{tag}"
        resp = self._client.delete(url)
        resp.raise_for_status()
        return resp.json()

    def get_image_storage_api_images_storage_get(self):
        """Get Image Storage"""
        url = self.base_url + "/api/images/storage"
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    def compress_all_images_api_images_storage_compress_post(self):
        """Compress All Images"""
        url = self.base_url + "/api/images/storage/compress"
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    def cleanup_to_target_api_images_storage_cleanup_to_target_post(self, target_free_mb: Any = None, dry_run: Any = None):
        """Cleanup To Target"""
        url = self.base_url + "/api/images/storage/cleanup-to-target"
        params = {k: v for k, v in locals().items() if k in ['target_free_mb', 'dry_run'] and v is not None}
        if params:
            from urllib.parse import urlencode
            url += '?' + urlencode(params)
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    def health_dashboard_health_get(self, format: Any = None):
        """Health Dashboard"""
        url = self.base_url + "/health"
        params = {k: v for k, v in locals().items() if k in ['format'] and v is not None}
        if params:
            from urllib.parse import urlencode
            url += '?' + urlencode(params)
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    # --- logs ---

    def aggregate_logs_api_logs_aggregate_get(self, group_by: Any = None, start_date: Any = None, end_date: Any = None, period: Any = None):
        """Aggregate Logs"""
        url = self.base_url + "/api/logs/aggregate"
        params = {k: v for k, v in locals().items() if k in ['group_by', 'start_date', 'end_date', 'period'] and v is not None}
        if params:
            from urllib.parse import urlencode
            url += '?' + urlencode(params)
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    def export_logs_api_logs_export_get(self, format: Any = None, page: Any = None, page_size: Any = None, fields: Any = None, type: Any = None, start_date: Any = None, end_date: Any = None):
        """Export Logs"""
        url = self.base_url + "/api/logs/export"
        params = {k: v for k, v in locals().items() if k in ['format', 'page', 'page_size', 'fields', 'type', 'start_date', 'end_date'] and v is not None}
        if params:
            from urllib.parse import urlencode
            url += '?' + urlencode(params)
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    def slow_queries_api_logs_slow_queries_get(self, start_date: Any = None, end_date: Any = None, threshold_ms: Any = None):
        """Slow Queries"""
        url = self.base_url + "/api/logs/slow-queries"
        params = {k: v for k, v in locals().items() if k in ['start_date', 'end_date', 'threshold_ms'] and v is not None}
        if params:
            from urllib.parse import urlencode
            url += '?' + urlencode(params)
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    # --- tracing ---

    def get_traces_api_tracing_traces_get(self, limit: Any = None, slow_only: Any = None):
        """Get Traces"""
        url = self.base_url + "/api/tracing/traces"
        params = {k: v for k, v in locals().items() if k in ['limit', 'slow_only'] and v is not None}
        if params:
            from urllib.parse import urlencode
            url += '?' + urlencode(params)
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    def get_tracing_stats_api_tracing_stats_get(self):
        """Get Tracing Stats"""
        url = self.base_url + "/api/tracing/stats"
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json()
