# 多语言接入示例

完整可运行的接入代码，覆盖图片生成、编辑、任务轮询、错误处理。

## 目录

- [Python](#python)
- [Node.js](#nodejs)
- [Go](#go)
- [curl](#curl)
- [图片任务轮询（异步）](#图片任务轮询异步)
- [错误处理最佳实践](#错误处理最佳实践)

---

## Python

### 同步图片生成（直连接口）

```python
import base64
import requests

BASE = "http://localhost:23456"
HEADERS = {"Authorization": "Bearer chatgpt2api"}

def generate_image(prompt: str, n: int = 1) -> list[str]:
    """同步调用图片生成接口，返回 base64 图片列表。"""
    resp = requests.post(
        f"{BASE}/v1/images/generations",
        headers={**HEADERS, "Content-Type": "application/json"},
        json={"model": "gpt-image-2", "prompt": prompt, "n": n, "response_format": "b64_json"},
        timeout=180,
    )
    resp.raise_for_status()
    return [item["b64_json"] for item in resp.json()["data"]]

images = generate_image("一张极简产品海报")
with open("output.png", "wb") as f:
    f.write(base64.b64decode(images[0]))
```

### 图片编辑

> **支持一次多张参考图**：`/v1/images/edits` 可同时传入多张参考图做合成/多图编辑。multipart 通过重复 `image` 字段传多张；JSON 通过 `images` 数组传多张。

```python
def edit_image(image_path: str, prompt: str) -> str:
    with open(image_path, "rb") as f:
        resp = requests.post(
            f"{BASE}/v1/images/edits",
            headers=HEADERS,
            files={"image": f},
            data={"model": "gpt-image-2", "prompt": prompt, "n": 1},
            timeout=180,
        )
    resp.raise_for_status()
    return resp.json()["data"][0]["b64_json"]
```

```python
def edit_with_multiple_references(image_paths: list[str], prompt: str) -> str:
    """多参考图编辑：同一 image 字段传多个文件对象。"""
    opened = [open(p, "rb") for p in image_paths]
    try:
        resp = requests.post(
            f"{BASE}/v1/images/edits",
            headers=HEADERS,
            files=[("image", f) for f in opened],  # 重复 image 字段 = 多参考图
            data={"model": "gpt-image-2", "prompt": prompt, "n": 1},
            timeout=180,
        )
        resp.raise_for_status()
        return resp.json()["data"][0]["b64_json"]
    finally:
        for f in opened:
            f.close()
```

### 异步任务 + 轮询（推荐生产用法）

```python
import time
import requests

BASE = "http://localhost:23456"
HEADERS = {"Authorization": "Bearer chatgpt2api"}


class ImageTaskError(Exception):
    pass


def submit_generation(prompt: str, task_id: str | None = None) -> str:
    """提交异步图片生成任务，返回 task_id。"""
    task_id = task_id or f"img-{int(time.time() * 1000)}"
    resp = requests.post(
        f"{BASE}/api/image-tasks/generations",
        headers={**HEADERS, "Content-Type": "application/json"},
        json={"client_task_id": task_id, "prompt": prompt, "model": "gpt-image-2"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["id"]


def poll_task(task_id: str, timeout: float = 180, interval: float = 3) -> list:
    """轮询任务直到成功/失败/超时，返回 data 列表。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = requests.get(f"{BASE}/api/image-tasks?ids={task_id}", headers=HEADERS, timeout=30)
        resp.raise_for_status()
        items = resp.json().get("items") or []
        if not items:
            raise ImageTaskError(f"任务不存在: {task_id}")
        task = items[0]
        status = task["status"]
        if status == "success":
            return task.get("data") or []
        if status == "error":
            raise ImageTaskError(task.get("error") or "任务失败")
        time.sleep(interval)

    # 超时后请求继续等待（resume-poll）
    resp = requests.post(
        f"{BASE}/api/image-tasks/{task_id}/resume-poll",
        headers={**HEADERS, "Content-Type": "application/json"},
        json={"extra_timeout_secs": 60},
        timeout=90,
    )
    resp.raise_for_status()
    task = resp.json()
    if task["status"] == "success":
        return task.get("data") or []
    raise TimeoutError(f"任务超时: {task_id}")


def generate_image_async(prompt: str) -> list:
    task_id = submit_generation(prompt)
    return poll_task(task_id)
```

### 文本补全

```python
def chat(messages: list, model: str = "gpt-5-mini") -> str:
    resp = requests.post(
        f"{BASE}/v1/chat/completions",
        headers={**HEADERS, "Content-Type": "application/json"},
        json={"model": model, "messages": messages},
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]
```

---

## Node.js

```javascript
const BASE = "http://localhost:23456";
const HEADERS = { Authorization: "Bearer chatgpt2api", "Content-Type": "application/json" };

async function generateImage(prompt, n = 1) {
  const resp = await fetch(`${BASE}/v1/images/generations`, {
    method: "POST",
    headers: HEADERS,
    body: JSON.stringify({ model: "gpt-image-2", prompt, n, response_format: "b64_json" }),
  });
  if (!resp.ok) throw new Error(await resp.text());
  const data = await resp.json();
  return data.data.map((item) => item.b64_json);
}

// 异步任务轮询
async function submitGeneration(prompt) {
  const taskId = `img-${Date.now()}`;
  const resp = await fetch(`${BASE}/api/image-tasks/generations`, {
    method: "POST",
    headers: HEADERS,
    body: JSON.stringify({ client_task_id: taskId, prompt, model: "gpt-image-2" }),
  });
  if (!resp.ok) throw new Error(await resp.text());
  return (await resp.json()).id;
}

async function pollTask(taskId, timeout = 180000, interval = 3000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const resp = await fetch(`${BASE}/api/image-tasks?ids=${taskId}`, { headers: HEADERS });
    if (!resp.ok) throw new Error(await resp.text());
    const { items } = await resp.json();
    if (!items.length) throw new Error(`任务不存在: ${taskId}`);
    const task = items[0];
    if (task.status === "success") return task.data;
    if (task.status === "error") throw new Error(task.error);
    await new Promise((r) => setTimeout(r, interval));
  }
  throw new Error(`任务超时: ${taskId}`);
}
```

---

## Go

```go
package main

import (
    "bytes"
    "encoding/json"
    "fmt"
    "net/http"
    "time"
)

const base = "http://localhost:23456"
const authKey = "chatgpt2api"

func post(path string, payload map[string]interface{}) (map[string]interface{}, error) {
    body, _ := json.Marshal(payload)
    req, _ := http.NewRequest("POST", base+path, bytes.NewReader(body))
    req.Header.Set("Authorization", "Bearer "+authKey)
    req.Header.Set("Content-Type", "application/json")
    resp, err := (&http.Client{Timeout: 180 * time.Second}).Do(req)
    if err != nil {
        return nil, err
    }
    defer resp.Body.Close()
    var result map[string]interface{}
    json.NewDecoder(resp.Body).Decode(&result)
    return result, nil
}

func generateImage(prompt string) error {
    result, err := post("/v1/images/generations", map[string]interface{}{
        "model": "gpt-image-2", "prompt": prompt, "n": 1,
    })
    if err != nil {
        return err
    }
    fmt.Println(result)
    return nil
}
```

---

## curl

```bash
# 图片生成
curl http://localhost:23456/v1/images/generations \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer chatgpt2api" \
  -d '{"model":"gpt-image-2","prompt":"一张极简产品海报","n":1,"response_format":"b64_json"}'

# 图片编辑（文件上传）
curl http://localhost:23456/v1/images/edits \
  -H "Authorization: Bearer chatgpt2api" \
  -F "model=gpt-image-2" \
  -F "prompt=改成赛博朋克夜景" \
  -F "image=@./input.png"

# 图片编辑（多参考图 - 文件上传）：重复 image 字段
curl http://localhost:23456/v1/images/edits \
  -H "Authorization: Bearer chatgpt2api" \
  -F "model=gpt-image-2" \
  -F "prompt=把图1的人物放进图2的场景" \
  -F "image=@./person.png" \
  -F "image=@./scene.png"

# 图片编辑（URL 引用）
curl http://localhost:23456/v1/images/edits \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer chatgpt2api" \
  -d '{"model":"gpt-image-2","prompt":"改成赛博朋克夜景","images":[{"image_url":"https://example.com/input.png"}]}'

# 图片编辑（多参考图 - URL 引用）：images 数组可含多张
curl http://localhost:23456/v1/images/edits \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer chatgpt2api" \
  -d '{"model":"gpt-image-2","prompt":"合并两张参考图","images":[{"image_url":"https://example.com/a.png"},{"image_url":"https://example.com/b.png"}]}'

# 提交异步任务
curl http://localhost:23456/api/image-tasks/generations \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer chatgpt2api" \
  -d '{"client_task_id":"img-001","prompt":"未来城市","model":"gpt-image-2"}'

# 轮询任务
curl "http://localhost:23456/api/image-tasks?ids=img-001" \
  -H "Authorization: Bearer chatgpt2api"
```

---

## 错误处理最佳实践

### 错误类型识别

```python
def call_with_retry(func, max_retries=3):
    for attempt in range(max_retries):
        try:
            return func()
        except requests.HTTPError as e:
            status = e.response.status_code
            if status == 401:
                raise  # 鉴权失败，不重试
            if status == 429:
                # 配额不足，等待后重试（指数退避）
                time.sleep(min(2 ** attempt * 10, 60))
                continue
            if status >= 500:
                # 上游错误，短暂等待后重试
                time.sleep(2 ** attempt)
                continue
            raise  # 其他错误不重试
    raise RuntimeError("重试次数用尽")
```

### 请求追踪排障

```python
resp = requests.post(url, headers=headers, json=payload)
request_id = resp.headers.get("x-request-id")
duration = resp.headers.get("x-response-time-ms")
print(f"请求 {request_id} 耗时 {duration}ms")
# 出现错误时，把 request_id 提供给运维，可在日志中串联整个调用链
```
