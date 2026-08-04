# ChatGPT2API 接口接入文档

> 面向调用方/集成方的完整接入指南。所有接口与 OpenAI 协议兼容，可直接用 OpenAI SDK 或任意 HTTP 客户端接入。

## 基本信息

| 项目 | 值 |
|------|-----|
| 服务地址 | `http://localhost:23456` |
| OpenAI Base URL | `http://localhost:23456/v1` |
| 鉴权方式 | `Authorization: Bearer <auth-key>` |
| 默认 auth-key | `chatgpt2api`（生产环境请修改） |
| 请求格式 | `application/json`（图片编辑支持 `multipart/form-data`） |

## 快速开始

### 1. 验证连通性

```bash
curl http://localhost:23456/v1/models \
  -H "Authorization: Bearer chatgpt2api"
```

### 2. OpenAI SDK 接入（Python）

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:23456/v1",
    api_key="chatgpt2api",
)

# 列出模型
models = client.models.list()
print([m.id for m in models.data])

# 图片生成
resp = client.images.generate(
    model="gpt-image-2",
    prompt="一张极简产品海报",
    n=1,
)
print(resp.data[0].b64_json[:50])
```

### 3. Node.js SDK 接入

```javascript
import OpenAI from "openai";

const client = new OpenAI({
  baseURL: "http://localhost:23456/v1",
  apiKey: "chatgpt2api",
});

const resp = await client.images.generate({
  model: "gpt-image-2",
  prompt: "一张极简产品海报",
  n: 1,
});
console.log(resp.data[0].b64_json.slice(0, 50));
```

## 可用模型

通过 `GET /v1/models` 动态获取，常用：

| 模型 | 用途 | 适用账号 |
|------|------|---------|
| `gpt-image-2` | 图片生成/编辑（推荐） | free / Plus / Pro |
| `codex-gpt-image-2` | Codex 画图（更高质量） | Plus / Team / Pro |
| `gpt-5` / `gpt-5-1` / `gpt-5-2` / `gpt-5-3` | 文本/搜索 | 全部 |
| `gpt-5-mini` / `gpt-5-3-mini` | 轻量文本 | 全部 |

**free 账号图片配额**：每天约 5 张，用完后自动限流（`You've hit the Free plan limit`），系统会自动切换到下一个可用账号。

## 核心接口

详细接口契约见：
- [openapi.yaml](./openapi.yaml) — OpenAPI 3.0 规范（可导入 Swagger UI / Postman）
- [examples.md](./examples.md) — 多语言完整示例（含图片任务轮询代码）
- [error-codes.md](./error-codes.md) — 错误码与错误处理
- [image-generation-protocol.md](./image-generation-protocol.md) — ChatGPT 图片生成协议蓝图（逆向分析）
- [image-upload-protocol.md](./image-upload-protocol.md) — ChatGPT 图片上传协议蓝图（逆向分析）

## 通用约定

### 错误格式

所有错误统一为 OpenAI 兼容结构：

```json
{
  "error": {
    "message": "错误描述",
    "type": "insufficient_quota",
    "param": null,
    "code": "insufficient_quota"
  }
}
```

### 状态码

| 状态码 | 含义 |
|--------|------|
| 200 | 成功 |
| 400 | 参数错误 |
| 401 | 鉴权失败（auth-key 错误） |
| 429 | 限流 / 配额不足（`no available image quota`） |
| 502 | 上游错误 |
| 500 | 服务器内部错误 |

### 请求追踪

每个响应带两个头用于排障：

| 响应头 | 说明 |
|--------|------|
| `X-Request-ID` | 请求唯一 ID，可在日志中按 ID 串联整个链路 |
| `X-Response-Time-Ms` | 该请求处理耗时（毫秒） |

### 可观测性

| 端点 | 说明 |
|------|------|
| `GET /metrics` | Prometheus 指标（请求计数/延迟/错误率，需鉴权） |
| `GET /api/dashboard/latency` | 请求延迟统计（需鉴权） |

## 图片任务轮询

图片生成为异步任务，推荐轮询模式（详见 [examples.md](./examples.md) 的完整轮询代码）：

```python
import time
import requests

BASE = "http://localhost:23456"
HEADERS = {"Authorization": "Bearer chatgpt2api"}

def generate_image_sync(prompt, timeout=180):
    # 1. 提交任务
    r = requests.post(
        f"{BASE}/api/image-tasks/generations",
        headers=HEADERS,
        json={"client_task_id": f"img-{int(time.time())}", "prompt": prompt, "model": "gpt-image-2"},
    )
    r.raise_for_status()
    task_id = r.json()["id"]

    # 2. 轮询直到完成
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = requests.get(f"{BASE}/api/image-tasks?ids={task_id}", headers=HEADERS)
        task = r.json()["items"][0]
        if task["status"] == "success":
            return task["data"]
        if task["status"] == "error":
            raise RuntimeError(task["error"])
        time.sleep(3)
    raise TimeoutError("图片生成超时")
```
