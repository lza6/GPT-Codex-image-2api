# 错误码与错误处理

所有错误统一为 OpenAI 兼容结构：

```json
{
  "error": {
    "message": "错误描述",
    "type": "错误类型",
    "param": null,
    "code": "错误码"
  }
}
```

## 错误码表

| HTTP 状态码 | code | type | 含义 | 处理建议 |
|------------|------|------|------|---------|
| 400 | `invalid_request_error` | `invalid_request_error` | 参数错误（缺少必填字段、格式错误） | 检查请求参数，不重试 |
| 401 | `invalid_api_key` | `authentication_error` | 鉴权失败（auth-key 错误或失效） | 检查 auth-key，不重试 |
| 429 | `insufficient_quota` | `insufficient_quota` | 号池配额不足（`no available image quota`） | 等待配额恢复或补充账号，可指数退避重试 |
| 429 | `rate_limit_global` | `rate_limit_error` | 触发全局限流 | 降低请求频率，等待后重试 |
| 429 | `rate_limit_ip` | `rate_limit_error` | 触发单 IP 限流 | 降低该 IP 请求频率 |
| 500 | `internal_error` | `api_error` | 服务器内部错误 | 可短暂等待后重试 |
| 502 | `upstream_error` | `server_error` | 上游 OpenAI 调用失败 | 可短暂等待后重试（系统会自动切换账号） |
| 502 | `UpstreamHTTPError` | `server_error` | 上游返回非 2xx（含上游 429/5xx） | 系统已自动切换账号重试，若仍失败检查号池 |

## 典型错误场景

### 1. 鉴权失败

```json
{
  "error": {
    "message": "密钥无效或已失效，请重新登录",
    "type": "authentication_error",
    "param": null,
    "code": "invalid_api_key"
  }
}
```

**处理**：核对 `Authorization: Bearer <auth-key>` 是否正确。auth-key 在 `config.json` 的 `auth-key` 字段。

### 2. 号池配额不足

```json
{
  "error": {
    "message": "no available image quota",
    "type": "insufficient_quota",
    "param": null,
    "code": "insufficient_quota"
  }
}
```

**处理**：所有可用账号配额已耗尽。等待配额自动恢复，或在号池管理中补充账号。

### 3. 上游熔断

当某账号连续失败达到熔断阈值（默认 5 次），熔断器会**主动跳过该账号**，快速失败而不是让请求排队打到坏账号。冷却期（默认 30s）后半开试探恢复。对调用方透明——系统会自动切换到健康账号。

### 4. 限流

```json
{
  "error": {
    "message": "rate limit exceeded",
    "type": "rate_limit_error",
    "param": null,
    "code": "rate_limit_global"
  }
}
```

**处理**：降低请求频率。响应头含 `Retry-After: 1`，按提示等待后重试。

## 重试策略建议

| 错误 | 是否重试 | 策略 |
|------|---------|------|
| 401 鉴权失败 | ❌ 不重试 | 修复凭证 |
| 400 参数错误 | ❌ 不重试 | 修复参数 |
| 429 配额不足 | ✅ 可重试 | 指数退避（10s → 20s → 40s，上限 60s） |
| 429 限流 | ✅ 可重试 | 按 `Retry-After` 等待 |
| 5xx 上游错误 | ✅ 可重试 | 短暂退避（1s → 2s → 4s） |

## 排障：请求追踪

每个响应含 `X-Request-ID`，出现错误时记录该 ID 提供给运维，可在日志中按 ID 串联整个调用链路（入口 → 账号调度 → 上游调用 → 错误）。
