# ChatGPT 图片生成协议蓝图

> 基于 ChatGPT Web 端逆向分析（源代码 + HAR 抓包）整理的完整协议文档。
> 适用于 free 账号和 Plus/Pro 账号的图片生成/编辑。

## 账号类型与配额

| 账号类型 | 图片配额 | 重置周期 | 特点 |
|---------|---------|---------|------|
| free | 服务端下发（`limits_progress.limit`） | 双窗口：5 小时 + 周 | `plan_type="free"`，`subscription_plan="chatgptfreeplan"` |
| Plus/Pro | 更多 | 每小时/每天 | `plan_type="plus"` / `"pro"` |

**free 账号限流数据结构**（服务端下发，非字面错误文本）：
```json
{
  "model_limits": [{"model_slug": "...", "resets_after": "..."}],
  "blocked_features": [{"name": "image_gen", "block_reason": "...", "resets_after": "..."}],
  "limits_progress": [{"feature_name": "image_gen", "limit": 5, "remaining": 0, "resets_after": "..."}]
}
```

**free 账号限流错误**（客户端展示）：
```
"You've hit the Free plan limit for image generations requests.
You can create more images when the limit resets in 40 minutes."
```

**处理策略**：
1. 捕获 429 / `rate_limit` / `blocked_features[name=="image_gen"]`
2. 读 `resets_after`（兼容 `reset_after`）确定重试时机
3. 自动切换到下一个可用账号（多账号池）
4. 如果没有可用账号，返回 429 `rate_limit_exceeded` + `resets_after`

## 核心端点

### 1. 准备对话（获取 conduit token）

```
POST /backend-api/f/conversation/prepare
```

**请求体**：
```json
{
  "action": "next",
  "fork_from_shared_post": false,
  "parent_message_id": "<uuid>",
  "model": "gpt-5-4-t-mini",
  "client_prepare_state": "success",
  "timezone_offset_min": -480,
  "timezone": "Asia/Shanghai",
  "conversation_mode": {"kind": "primary_assistant"},
  "system_hints": ["picture_v2"],
  "partial_query": {
    "id": "<uuid>",
    "author": {"role": "user"},
    "content": {"content_type": "text", "parts": ["<prompt>"]}
  },
  "supports_buffering": true,
  "supported_encodings": ["v1"],
  "client_contextual_info": {"app_name": "chatgpt.com"}
}
```

**响应**：`x-conduit-token` 头（用于后续 `/f/conversation` 请求）

### 2. 流式生图

```
POST /backend-api/f/conversation
```

**请求体**：
```json
{
  "action": "next",
  "messages": [{
    "id": "<uuid>",
    "author": {"role": "user"},
    "create_time": <unix_timestamp>,
    "content": {
      "content_type": "text",
      "parts": ["@图片 <prompt>"]
    },
    "metadata": {
      "system_hints": ["picture_v2", "reason"],
      "serialization_metadata": {
        "custom_symbol_offsets": [{
          "id": "picture_v2",
          "symbol": "ecosystemMention",
          "startIndex": 0,
          "endIndex": 5
        }]
      }
    }
  }],
  "parent_message_id": "client-created-root",
  "model": "gpt-5-4-t-mini",
  "client_prepare_state": "success",
  "timezone_offset_min": -480,
  "timezone": "Asia/Shanghai",
  "conversation_mode": {"kind": "primary_assistant"},
  "enable_message_followups": true,
  "system_hints": ["picture_v2", "reason"],
  "supports_buffering": true,
  "supported_encodings": ["v1"],
  "client_contextual_info": {
    "is_dark_mode": false,
    "time_since_loaded": 992,
    "page_height": 906,
    "page_width": 1020,
    "pixel_ratio": 1.5,
    "screen_height": 1067,
    "screen_width": 1707,
    "app_name": "chatgpt.com",
    "has_web_push_capabilities": true,
    "web_push_notification_permission": "default"
  },
  "paragen_cot_summary_display_override": "allow",
  "force_parallel_switch": "auto",
  "local_function_names": ["local.continue_in_work"]
}
```

**关键参数说明**：

| 参数 | free 账号值 | Plus/Pro 值 | 说明 |
|------|------------|------------|------|
| `model` | `"auto"` | `gpt-5-5` / `gpt-5-5-mini` | free 用 `auto` 让上游选择模型 |
| `system_hints` | `["picture_v2", "reason"]` | 相同 | `picture_v2` 触发图片生成工具（`image_gen`） |
| `content.parts[0]` | `"@图片 <prompt>"` | 相同 | `@图片` 前缀触发 `ecosystemMention` |

**响应**：SSE 流（`text/event-stream`）

### 3. 轮询对话（获取图片）

```
GET /backend-api/conversation/{conversation_id}
```

**响应结构**：
```json
{
  "mapping": {
    "<message_id>": {
      "message": {
        "author": {"role": "assistant"},
        "content": {
          "content_type": "multimodal_text",
          "parts": [{
            "content_type": "image_asset_pointer",
            "asset_pointer": "file-service://file_00000000..."
          }]
        },
        "metadata": {
          "image_gen_async": true,
          "image_gen_task_id": "<task_id>",
          "image_gen_multi_stream": false
        }
      }
    }
  }
}
```

**file_id 提取**：
- `asset_pointer` 格式：`file-service://file_00000000...` 或 `sediment://file_00000000...`
- `file_id` = `file_00000000...`（去掉前缀）

### 4. 下载图片

```
GET /backend-api/files/download/{file_id}?conversation_id={conversation_id}&inline=false&download_intent=false
```

**响应**：
```json
{
  "status": "success",
  "download_url": "https://chatgpt.com/backend-api/estuary/content?id=<file_id>&ts=<ts>&p=fs&cid=1&sig=<sig>&v=0",
  "metadata": null,
  "file_name": "<user_id>/<uuid>.png",
  "creation_time": null,
  "no_auth_user_upload": null,
  "mime_type": null,
  "file_size_bytes": 2108801
}
```

**注意**：`conversation_id` 参数是**可选**的（子代理扫描证实），但带上可以避免某些边缘情况的 404。

### 5. 下载图片内容（estuary）

```
GET /backend-api/estuary/content?id={file_id}&ts={ts}&p=fs&cid=1&sig={sig}&v=0
```

**响应**：图片二进制内容（`image/png`）

## 错误处理

### free 账号限流

**错误文本**：
```
"You've hit the Free plan limit for image generations requests.
You can create more images when the limit resets in 40 minutes."
```

**处理策略**：
1. 识别错误文本中的 `free plan limit` / `rate limit` / `今日上限`
2. 标记当前账号为"限流"状态
3. 自动切换到下一个可用账号
4. 如果没有可用账号，返回 429 `rate_limit_exceeded`

### 内容政策违规

**错误文本**：出现在 assistant 消息的文本中（如"抱歉，我不能生成..."）

**处理策略**：返回 400 `content_policy_violation`，不重试。

### 轮询超时

**默认超时**：600 秒（10 分钟）

**处理策略**：返回 `conversation_id`，调用方可后续重试。

## 模型映射

| 客户端模型 | 上游模型（free） | 上游模型（Plus/Pro） | 适用账号 | 说明 |
|-----------|-----------------|---------------------|---------|------|
| `gpt-image-2` | `"auto"` | `gpt-5-5` | 全部 | 标准图片生成 |
| `codex-gpt-image-2` | — | `codex-gpt-image-2` | Plus/Team/Pro | Codex 画图（更高质量） |

**free 账号模型选择**：
- 生图请求用 `"auto"`（让上游选择模型），不切换 `model` 字段
- 靠 `system_hints: ["picture_v2"]` 激活生图工具
- free 账号 `maxTokens=16384`（付费 128000）

## 完整流程图

```
1. POST /backend-api/f/conversation/prepare
   → 获取 x-conduit-token（可选，用于加速后续请求）

2. POST /backend-api/f/conversation (SSE)
   → 请求头：x-conduit-token + x-oai-turn-trace-id
   → 流式接收事件（message/done/error/moderation）
   → 提取 conversation_id + metadata.image_gen_async

3. GET /backend-api/conversation/{conversation_id}
   → 轮询直到 image_asset_pointer 出现（sediment://file-...）
   → 按 metadata.poll_interval_ms 间隔轮询
   → 提取 file_id（剥掉 sediment:// 前缀）

4. GET /backend-api/files/download/{file_id}?conversation_id=<id>&inline=false
   → 获取 download_url（estuary 签名 URL）

5. GET /backend-api/estuary/content?id=<file_id>&ts=<ts>&sig=<sig>
   → 下载图片二进制
```

## 与 ChatGPT2API 的映射

| ChatGPT Web 端 | ChatGPT2API | 说明 |
|---------------|-------------|------|
| `POST /backend-api/f/conversation/prepare` | `OpenAIBackendAPI._prepare_image_conversation` | 获取 conduit token（可选） |
| `POST /backend-api/f/conversation` | `OpenAIBackendAPI._stream_picture_conversation` | SSE 流式生图 |
| `GET /backend-api/conversation/{id}` | `OpenAIBackendAPI._poll_image_results` | 轮询图片（按 `poll_interval_ms`） |
| `GET /backend-api/files/download/{id}` | `OpenAIBackendAPI._get_file_download_url` | 获取下载 URL（`conversation_id` 可选） |
| `GET /backend-api/estuary/content` | `OpenAIBackendAPI.download_image_bytes` | 下载图片内容 |

## 关键实现要点（子代理扫描结论）

1. **free 生图**：`POST /f/conversation`，`model="auto"`，`system_hints=["picture_v2"]`，先发 `/f/conversation/prepare` 拿 `conduit_token`（可选）
2. **SSE 解析**：`metadata.image_gen_async === true` 标记异步任务，`image_asset_pointer` 的 `asset_pointer="sediment://file-..."`
3. **轮询**：按 `metadata.poll_interval_ms`（`imageGenPollingIntervalMs`）间隔轮询至 `ghostrider_status == "final"`
4. **取图**：`GET /files/download/{file_id}?inline=true&conversation_id=<id>`，`file_id` 剥掉 `sediment://` 前缀
5. **限流**：捕获 429 / `rate_limit` / `blocked_features[name=="image_gen"]`，读 `resets_after` 定重试时机；free 判定 `plan_type=="free"`

## 参考来源

- ChatGPT Web 端源代码（`4813494d-f1puh0u8tu19x3d1.js`）
- HAR 抓包（`chatgpt.com.har`）
- 用户提供的协议文档（`发送请求的是这样的包括流式创建图片等等的.txt`）
