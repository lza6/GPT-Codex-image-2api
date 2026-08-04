# ChatGPT 图片上传协议蓝图

> 基于 ChatGPT Web 端逆向分析（用户提供的抓包文档）整理的完整上传协议。
> 适用于图片编辑（img2img）和文件上传。

## 上传流程

### 1. 请求上传凭证

```
POST /backend-api/files
```

**请求体**：
```json
{
  "file_name": "image.jpg",
  "file_size": 267939,
  "use_case": "multimodal",
  "timezone_offset_min": -480,
  "reset_rate_limits": false,
  "supports_direct_azure_multipart": true,
  "mime_type": "image/jpeg",
  "entry_surface": "chat_composer",
  "selection_method": "file_picker",
  "client_resolved_mime_type": "image/jpeg",
  "mime_resolution_source": "filename_extension",
  "store_in_library": true,
  "library_persistence_mode": "opportunistic"
}
```

**响应**：
```json
{
  "file_id": "file_00000000726c824392d33882d2b61379",
  "upload_url": "https://sdmntprukwest.oaiusercontent.com/files/00000000-726c-8243-92d3-3882d2b61379/raw?se=...&sig=...",
  "expires_at": "2026-08-03T17:24:23Z"
}
```

### 2. 上传文件内容（Azure Blob）

```
PUT {upload_url}
```

**请求头**：
```
Content-Type: image/jpeg
Content-Length: 267939
Origin: https://chatgpt.com
Referer: https://chatgpt.com/
```

**请求体**：图片二进制内容

**响应**：`201 Created`（Azure Blob 上传成功）

### 3. 确认上传（处理上传流）

```
POST /backend-api/files/process_upload_stream
```

**请求体**：
```json
{
  "file_id": "file_00000000726c824392d33882d2b61379",
  "use_case": "multimodal",
  "index_for_retrieval": false,
  "file_name": "image.jpg",
  "library_persistence_mode": "opportunistic",
  "entry_surface": "chat_composer",
  "metadata": {
    "store_in_library": true,
    "is_temporary_chat": false,
    "library_eligibility_reason": "eligible",
    "is_project_thread": false
  }
}
```

**响应**：
```json
{
  "file_id": "file_00000000726c824392d33882d2b61379",
  "status": "success"
}
```

### 4. 获取文件信息（可选）

```
GET /backend-api/files/{file_id}/simple
```

**响应**：
```json
{
  "file_id": "file_00000000726c824392d33882d2b61379",
  "file_name": "image.jpg",
  "file_size_bytes": 267939,
  "mime_type": "image/jpeg",
  "use_case": "multimodal",
  "created_at": "2026-08-03T17:24:23Z"
}
```

### 5. 下载文件

```
GET /backend-api/files/download/{file_id}?download_intent=false
```

**响应**：
```json
{
  "status": "success",
  "download_url": "https://sdmntprukwest.oaiusercontent.com/files/.../raw?se=...&sig=...",
  "file_name": "image.jpg",
  "file_size_bytes": 267939,
  "mime_type": "image/jpeg"
}
```

## 图片编辑（img2img）

图片编辑使用与生图相同的 `/f/conversation` 端点，但 `content.parts` 中包含上传的图片引用：

```json
{
  "messages": [{
    "id": "<uuid>",
    "author": {"role": "user"},
    "content": {
      "content_type": "multimodal_text",
      "parts": [
        {"content_type": "text", "text": "<prompt>"},
        {"content_type": "image_asset_pointer", "asset_pointer": "file-service://file_00000000726c824392d33882d2b61379"}
      ]
    }
  }],
  "system_hints": ["picture_v2"],
  ...
}
```

**图片编辑类型**：
- `inpainting`：局部重绘（需要 `original_file_id` + `mask_file_id`）
- `transformation`：风格转换（需要 `original_file_id`）
- `edit`：通用编辑（需要 `original_file_id`）

## 与 ChatGPT2API 的映射

| ChatGPT Web 端 | ChatGPT2API | 说明 |
|---------------|-------------|------|
| `POST /backend-api/files` | `OpenAIBackendAPI._upload_image` | 请求上传凭证 |
| `PUT {upload_url}` | `OpenAIBackendAPI._upload_image` | 上传文件内容（Azure Blob） |
| `POST /backend-api/files/process_upload_stream` | `OpenAIBackendAPI._upload_image` | 确认上传 |
| `GET /backend-api/files/download/{id}` | `OpenAIBackendAPI._get_file_download_url` | 获取下载 URL |
| `POST /f/conversation` (with image) | `OpenAIBackendAPI._stream_picture_conversation` | 图片编辑 |

## 参考来源

- 用户提供的抓包文档（`图片上传是这样的.txt`）
- ChatGPT Web 端源代码（`4813494d-f1puh0u8tu19x3d1.js`）
