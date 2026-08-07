# 开发者接入指南（对外调用）

> 本文档面向**要调用本服务的开发者**。当前服务已部署在腾讯云东京服务器，开箱即用。

---

## 一、访问地址（服务器）

| 用途 | 地址 | 说明 |
|------|------|------|
| **API Base（开发者用这个）** | `http://43.165.173.36:23456/v1` | OpenAI 兼容接口 |
| Web 控制台 | `http://43.165.173.36:23456` | 在线画图 / 账号管理 |
| 运维看板 | `http://43.165.173.36:23456/dashboard` | 调度健康度/用量/延迟（SSE 实时） |
| 注册控制台 | `http://43.165.173.36:23457` | GPT 自动注册（号池补给） |

> 内网/本地自部署时把 `43.165.173.36` 换成 `localhost` 即可。

---

## 二、鉴权（必带）

所有 AI 接口都需要请求头：

```http
Authorization: Bearer <auth-key>
```

当前服务器 auth-key（chatgpt2api）：

```
cg2api-8tbkFwuqBPLZ2cUuA12f8Ldvt2mkYNlO
```

> 注册控制台（23457）是另一个服务、另一个 key：`cg2reg-yMBLKDIzs0tqKHXcPAphKQYHyJuqBC8R`（仅管理用，开发者调图不需要）。

---

## 三、快速验证（30 秒）

```bash
# 1. 查可用模型
curl http://43.165.173.36:23456/v1/models \
  -H "Authorization: Bearer cg2api-8tbkFwuqBPLZ2cUuA12f8Ldvt2mkYNlO"
```

返回（当前实测）：

```json
{"data":[{"id":"auto"},{"id":"gpt-5-5"},{"id":"gpt-image-2"}, ...]}
```

---

## 四、核心接口（OpenAI 兼容）

### 1. 文生图 `POST /v1/images/generations`

```bash
curl http://43.165.173.36:23456/v1/images/generations \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer cg2api-8tbkFwuqBPLZ2cUuA12f8Ldvt2mkYNlO" \
  -d '{
    "model": "gpt-image-2",
    "prompt": "一只漂浮在太空里的猫，电影感打光",
    "n": 1,
    "size": "1024x1024",
    "response_format": "b64_json"
  }'
```

返回 `data[0].b64_json`（Base64 PNG，可直接解码保存）或 `data[0].url`。

### 2. 图生图 / 图片编辑 `POST /v1/images/edits`

```bash
# 方式 A：上传文件（multipart）
curl http://43.165.173.36:23456/v1/images/edits \
  -H "Authorization: Bearer cg2api-8tbkFwuqBPLZ2cUuA12f8Ldvt2mkYNlO" \
  -F "model=gpt-image-2" \
  -F "prompt=把这张图改成赛博朋克夜景风格" \
  -F "image=@./input.png"

# 方式 B：传图片 URL（JSON）
curl http://43.165.173.36:23456/v1/images/edits \
  -H "Authorization: Bearer cg2api-8tbkFwuqBPLZ2cUuA12f8Ldvt2mkYNlO" \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-image-2","prompt":"改成水彩风","images":[{"image_url":"https://.../in.png"}]}'
```

### 3. 对话 `POST /v1/chat/completions`（支持流式）

```bash
# 非流式
curl http://43.165.173.36:23456/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer cg2api-8tbkFwuqBPLZ2cUuA12f8Ldvt2mkYNlO" \
  -d '{"model":"auto","messages":[{"role":"user","content":"你好"}]}'

# 流式（SSE）
curl -N http://43.165.173.36:23456/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer cg2api-8tbkFwuqBPLZ2cUuA12f8Ldvt2mkYNlO" \
  -d '{"model":"auto","stream":true,"messages":[{"role":"user","content":"数到3"}]}'
```

> `model` 填 `auto` 让调度器自动选；也可填 `/v1/models` 返回的具体模型（如 `gpt-5-5`、`gpt-image-2`）。

---

## 五、客户端接入

### OpenAI Python SDK

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://43.165.173.36:23456/v1",
    api_key="cg2api-8tbkFwuqBPLZ2cUuA12f8Ldvt2mkYNlO",
)

# 文生图
img = client.images.generate(model="gpt-image-2", prompt="一只太空猫", n=1)
print(img.data[0].b64_json or img.data[0].url)

# 对话
resp = client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": "你好"}],
)
print(resp.choices[0].message.content)
```

### Cherry Studio / NextChat / LobeChat 等

- **接口类型**：OpenAI
- **API 地址 / Base URL**：`http://43.165.173.36:23456/v1`
- **API Key**：`cg2api-8tbkFwuqBPLZ2cUuA12f8Ldvt2mkYNlO`
- **模型**：`gpt-image-2`（画图）或 `auto`（对话）

### New API / One API 等中转

把本服务当作一个 OpenAI 上游渠道填入即可（Base URL + Key 同上）。

---

## 六、可用接口速查

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/v1/models` | 可用模型列表 |
| POST | `/v1/images/generations` | 文生图 |
| POST | `/v1/images/edits` | 图生图 / 图片编辑（文件或 URL） |
| POST | `/v1/chat/completions` | 对话（支持 `stream:true`） |
| POST | `/v1/responses` | Responses API |
| POST | `/v1/messages` | Anthropic 兼容对话 |
| GET | `/files/{path}` | 生成文件下载（需带 auth-key） |

> 已下线（v2.9.0 功能裁剪）：`/v1/search`、`/v1/ppt/generations`、`/v1/psd/generations` 返回 404。

---

## 七、错误码与排查

| 状态码 | 含义 | 处理 |
|--------|------|------|
| 401 | auth-key 缺失/错误 | 检查 `Authorization: Bearer <key>` 头 |
| 429 | 触发限流 | 降并发，稍后重试 |
| 404 | 端点不存在/已裁剪 | 对照第六节速查表 |
| 502/503 | 上游账号暂时不可用 | 服务自动切号重试，持续失败看 `/dashboard` |

排障入口：

- 看板：`http://43.165.173.36:23456/dashboard`（实时调度/熔断/用量）
- 健康：`curl http://43.165.173.36:23456/version` → `{"version":"2.9.0"}`

---

## 八、说明

- **每次请求新建会话**：对话/生图默认不带上文（防串号污染）；仅图片编辑（`/v1/images/edits`）保持上下文。
- **每号独立 IP**：后端号池走 kookeey 住宅代理，每个账号固定独立 IP，无需调用方关心代理。
- 本服务为逆向封装的内部工具，请勿用于商业/批量滥用场景。
