"""代理池管理 API。"""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from api.support import require_admin
from services.account_service import account_service
from services.proxy_pool import ProxySelectionStrategy, proxy_pool
from services.proxy_service import proxy_settings


class ProxyAddRequest(BaseModel):
    url: str
    weight: int = 1


class ProxyWeightRequest(BaseModel):
    url: str
    weight: int


class ProxyStrategyRequest(BaseModel):
    strategy: str


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/proxies")
    async def list_proxies(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {
            "proxies": proxy_pool.get_all(),
            "stats": proxy_pool.get_stats(),
        }

    @router.post("/api/proxies")
    async def add_proxy(body: ProxyAddRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        if not body.url:
            raise HTTPException(status_code=400, detail={"error": "url is required"})
        proxy_pool.add(body.url, weight=body.weight)
        return {"ok": True, "url": body.url, "weight": body.weight}

    @router.delete("/api/proxies/{url:path}")
    async def remove_proxy(url: str, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        proxy_pool.remove(url)
        return {"ok": True, "removed": url}

    @router.post("/api/proxies/weight")
    async def update_weight(body: ProxyWeightRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        proxy_pool.update_weight(body.url, body.weight)
        return {"ok": True}

    @router.post("/api/proxies/strategy")
    async def set_strategy(body: ProxyStrategyRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            strategy = ProxySelectionStrategy(body.strategy)
            proxy_pool.config.strategy = strategy
            return {"ok": True, "strategy": strategy.value}
        except ValueError:
            raise HTTPException(status_code=400, detail={"error": f"invalid strategy: {body.strategy}"}) from None

    @router.post("/api/proxies/health-check")
    async def trigger_health_check(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        proxy_pool.start_health_check()
        return {"ok": True}

    def _probe_egress_ip(account: dict | None) -> dict:
        """探测指定账号（按其代理配置）的出口 IP。"""
        from curl_cffi.requests import Session
        kwargs = proxy_settings.build_session_kwargs(account=account, impersonate="chrome110", verify=True)
        try:
            with Session(**kwargs) as session:
                resp = session.get("https://api.ipify.org?format=json", timeout=15)
                data = resp.json()
                return {
                    "ok": True,
                    "ip": data.get("ip", ""),
                    "proxy": (account or {}).get("proxy") or "direct",
                }
        except Exception as exc:
            return {
                "ok": False,
                "error": str(exc),
                "proxy": (account or {}).get("proxy") or "direct",
            }

    @router.post("/api/proxies/probe-ip")
    async def probe_egress_ip(body: dict | None = None, authorization: str | None = Header(default=None)):
        """探测当前服务（或指定 token 账号）的出口 IP。"""
        require_admin(authorization)
        account = None
        token = str((body or {}).get("token") or "").strip()
        if token:
            account = account_service.get_account(token)
        return await run_in_threadpool(_probe_egress_ip, account)

    @router.get("/api/proxies/egress-ip")
    async def get_egress_ip(authorization: str | None = Header(default=None)):
        """获取当前服务（默认代理配置）的出口 IP。"""
        require_admin(authorization)
        return await run_in_threadpool(_probe_egress_ip, None)

    return router
