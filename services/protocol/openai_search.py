from __future__ import annotations

from services.account_service import account_service
from services.openai_backend_api import SEARCH_MODEL, OpenAIBackendAPI
from services.protocol.conversation import is_upstream_instability_error

MODEL = SEARCH_MODEL


def handle(body: dict[str, object]) -> dict[str, object]:
    token = account_service.get_text_access_token()
    account = account_service.get_account(token) or {}
    # D7：搜索路径接熔断——OPEN 状态快速失败，不请求上游
    breaker = account_service._breaker_registry.get(token)
    if not breaker.allow_request():
        raise RuntimeError("search upstream circuit open: 熔断开启，搜索账号暂时不可用")
    backend = OpenAIBackendAPI(token)
    try:
        result = backend.search(str(body["prompt"]))
    except Exception as exc:
        # 仅上游抖动（5xx/超时/TLS/连接）记熔断失败；业务拒绝不记（防恶意输入熔断健康账号）
        if is_upstream_instability_error(str(exc)):
            breaker.record_failure()
        raise
    finally:
        backend.close()
    breaker.record_success()
    account_service.mark_text_used(token)
    result["_account_email"] = str(account.get("email") or "")
    return result
