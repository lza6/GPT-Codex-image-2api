"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  ChevronDown,
  Copy,
  FileArchive,
  FileText,
  KeyRound,
  ListChecks,
  type LucideIcon,
} from "lucide-react";
import { toast } from "sonner";

import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { copyText } from "@/lib/clipboard";
import webConfig from "@/constants/common-env";
import { getStoredAuthSession } from "@/store/auth";

type ParamRow = [string, string, string];

type ApiDoc = {
  title: string;
  method: string;
  path: string;
  icon: LucideIcon;
  input: ParamRow[];
  output: ParamRow[];
  example: (baseUrl: string, key: string) => string;
  response: string;
};

const docs: ApiDoc[] = [
  {
    title: "模型列表",
    method: "GET",
    path: "/v1/models",
    icon: ListChecks,
    input: [
      ["Authorization", "header", "Bearer <auth-key>，所有接口统一鉴权。"],
    ],
    output: [
      ["data", "array", "模型列表，包含 id、object、created、owned_by。"],
    ],
    example: (baseUrl: string, key: string) => `curl ${baseUrl}/models \\
  -H "Authorization: Bearer ${key}"`,
    response: `{
  "data": [
    { "id": "auto", "object": "model", "created": 1700000000, "owned_by": "chatgpt2api" },
    { "id": "gpt-image-2", "object": "model", "created": 1700000000, "owned_by": "chatgpt2api" },
    { "id": "gpt-5-3-mini", "object": "model", "created": 1700000000, "owned_by": "chatgpt2api" }
  ]
}`,
  },
  {
    title: "聊天补全",
    method: "POST",
    path: "/v1/chat/completions",
    icon: FileText,
    input: [
      ["model", "string", "模型名，如 auto、gpt-5-mini 等。"],
      ["messages", "array", "OpenAI 兼容消息数组，支持多轮对话。"],
      ["stream", "boolean", "可选，是否流式返回 SSE。"],
      ["n", "number", "可选，生成数量。"],
      ["modalities", "array", "可选，如 [\"text\"]。"],
    ],
    output: [
      ["id", "string", "响应 ID。"],
      ["choices", "array", "OpenAI 兼容 choices，含 message.content。"],
      ["usage", "object", "可选，token 使用统计。"],
      ["_account_email", "string", "本次使用的账号邮箱，用于排查。"],
    ],
    example: (baseUrl: string, key: string) => `curl ${baseUrl}/chat/completions \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer ${key}" \\
  -d '{
    "model": "auto",
    "messages": [
      {"role": "system", "content": "你是一个助手"},
      {"role": "user", "content": "你好，请介绍一下自己"}
    ],
    "stream": false
  }'`,
    response: `{
  "id": "chatcmpl-xxx",
  "object": "chat.completion",
  "created": 1700000000,
  "model": "auto",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "你好！我是 AI 助手，很高兴为你服务。"
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 20,
    "completion_tokens": 15,
    "total_tokens": 35
  },
  "_account_email": "xxx@outlook.com"
}`,
  },
  {
    title: "Responses API",
    method: "POST",
    path: "/v1/responses",
    icon: FileText,
    input: [
      ["model", "string", "模型名，如 auto、gpt-image-2（图片生成用）。"],
      ["input", "string | array | object", "用户输入内容。"],
      ["tools", "array", "可选，工具定义数组。"],
      ["stream", "boolean", "可选，是否流式返回。"],
    ],
    output: [
      ["id", "string", "响应 ID。"],
      ["output", "array", "输出内容列表。"],
      ["status", "string", "completed / in_progress / failed。"],
      ["_account_email", "string", "本次使用的账号邮箱。"],
    ],
    example: (baseUrl: string, key: string) => `curl ${baseUrl}/responses \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer ${key}" \\
  -d '{
    "model": "auto",
    "input": "生成一张未来城市图片"
  }'`,
    response: `{
  "id": "resp_xxx",
  "object": "response",
  "status": "completed",
  "output": [
    {
      "type": "message",
      "role": "assistant",
      "content": [
        { "type": "output_text", "text": "这是为您生成的未来城市图片：" },
        { "type": "image_url", "image_url": { "url": "https://chatgpt.com/backend-api/estuary/content?id=..." } }
      ]
    }
  ],
  "_account_email": "xxx@outlook.com"
}`,
  },
  {
    title: "文生图",
    method: "POST",
    path: "/v1/images/generations",
    icon: FileArchive,
    input: [
      ["prompt", "string", "图片生成提示词，必填。"],
      ["model", "string", "可选，默认 gpt-image-2。"],
      ["n", "number", "可选，生成数量，限制 1-4。"],
      ["size", "string", "可选，图片尺寸，如 1024x1024、1792x1024。"],
      ["quality", "string", "可选，默认 auto。"],
      ["response_format", "string", "可选，b64_json（默认）或 url。"],
      ["seed", "number", "可选，固定随机种子（实验性）。"],
    ],
    output: [
      ["data", "array", "图片结果列表。"],
      ["data[].b64_json", "string", "base64 编码的图片内容。"],
      ["data[].url", "string", "图片 URL（透传模式为上游直链，需 Proxy-Download 接口代理预览）。"],
      ["data[].revised_prompt", "string", "OpenAI 自动优化的提示词。"],
      ["data[].expires_at", "number", "透传模式下上游直链过期时间戳。"],
      ["usage", "object", "token 使用统计。"],
    ],
    example: (baseUrl: string, key: string) => `curl ${baseUrl}/images/generations \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer ${key}" \\
  -d '{
    "model": "gpt-image-2",
    "prompt": "一张极简产品海报，白色背景，居中展示",
    "n": 1,
    "size": "1024x1024",
    "response_format": "b64_json"
  }'`,
    response: `{
  "created": 1700000000,
  "data": [
    {
      "b64_json": "iVBORw0KGgoAAAANSUhEUg...（base64 编码的图片数据）",
      "url": "https://chatgpt.com/backend-api/estuary/content?id=file_xxx",
      "revised_prompt": "A minimalist product poster with white background, centered showcase",
      "expires_at": 1700003600
    }
  ],
  "usage": {
    "input_text_tokens": 15,
    "output_tokens": 1024
  }
}`,
  },
  {
    title: "图生图",
    method: "POST",
    path: "/v1/images/edits",
    icon: FileArchive,
    input: [
      ["image", "file", "参考图，multipart/form-data 上传。支持 PNG/JPG。"],
      ["prompt", "string", "编辑提示词，描述想要的修改。"],
      ["model", "string", "可选，默认 gpt-image-2。"],
      ["n", "number", "可选，生成数量，限制 1-4。"],
      ["size", "string", "可选，图片尺寸。"],
      ["quality", "string", "可选，默认 auto。"],
      ["mask", "file", "可选，透明遮罩图，指定编辑区域。"],
    ],
    output: [
      ["data", "array", "编辑后的图片结果列表，格式同文生图。"],
      ["data[].b64_json", "string", "base64 图片内容。"],
      ["data[].url", "string", "图片 URL。"],
      ["data[].revised_prompt", "string", "优化后的提示词。"],
    ],
    example: (baseUrl: string, key: string) => `curl ${baseUrl}/images/edits \\
  -H "Authorization: Bearer ${key}" \\
  -F "model=gpt-image-2" \\
  -F "prompt=改成赛博朋克夜景风格" \\
  -F "image=@./input.png" \\
  -F "mask=@./mask.png"`,
    response: `{
  "created": 1700000000,
  "data": [
    {
      "b64_json": "iVBORw0KGgo...（base64 编码的编辑后图片）",
      "url": "https://chatgpt.com/backend-api/estuary/content?id=file_yyy",
      "revised_prompt": "Cyberpunk night city style, neon lights, dark atmosphere",
      "expires_at": 1700003600
    }
  ],
  "usage": {
    "input_text_tokens": 12,
    "output_tokens": 1024
  }
}`,
  },
  {
    title: "文生图任务（异步轮询）",
    method: "POST",
    path: "/api/image-tasks/generations",
    icon: FileText,
    input: [
      ["client_task_id", "string", "客户端幂等任务 ID，必填。重复提交同 ID 返回已有任务。"],
      ["prompt", "string", "图片生成提示词。"],
      ["model", "string", "可选，默认 gpt-image-2。"],
      ["size", "string", "可选，图片尺寸。"],
      ["quality", "string", "可选，默认 auto。"],
      ["seed", "number", "可选，固定随机种子。"],
    ],
    output: [
      ["id", "string", "任务 ID，后续轮询用。"],
      ["status", "string", "queued / running / success / error。"],
      ["created_at", "string", "任务创建时间。"],
      ["updated_at", "string", "任务更新时间。"],
      ["data", "array", "status=success 时返回图片结果列表。"],
      ["error", "string", "status=error 时返回错误信息。"],
    ],
    example: (baseUrl: string, key: string) => `# 1. 提交任务
curl -X POST ${baseUrl.replace(/\/v1$/, "")}/api/image-tasks/generations \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer ${key}" \\
  -d '{
    "client_task_id": "my-task-001",
    "prompt": "红色圆形渐变背景",
    "model": "gpt-image-2",
    "size": "1024x1024"
  }'

# 2. 轮询结果（替换 task_id 为实际返回的 id）
curl ${baseUrl.replace(/\/v1$/, "")}/api/image-tasks?ids=task_xxx \\
  -H "Authorization: Bearer ${key}"

# 3. 续轮询（超时后加时等待）
curl -X POST ${baseUrl.replace(/\/v1$/, "")}/api/image-tasks/task_xxx/resume-poll \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer ${key}" \\
  -d '{"extra_timeout_secs": 60}'`,
    response: `{
  "id": "task_abc123",
  "status": "running",
  "created_at": "2026-08-09T07:00:00",
  "updated_at": "2026-08-09T07:00:00",
  "quality": "auto",
  "size": "1024x1024",
  "model": "gpt-image-2",
  "account_email": "xxx@outlook.com",
  "data": [],
  "error": ""
}

// 轮询成功后返回（status=success）：
{
  "id": "task_abc123",
  "status": "success",
  "data": [
    {
      "url": "https://chatgpt.com/backend-api/estuary/content?id=file_xxx",
      "revised_prompt": "Red circular gradient background",
      "expires_at": 1700003600
    }
  ],
  "duration_ms": 45200
}`,
  },
  {
    title: "图生图任务（异步轮询）",
    method: "POST",
    path: "/api/image-tasks/edits",
    icon: FileArchive,
    input: [
      ["client_task_id", "string", "客户端幂等任务 ID，必填。"],
      ["image", "file", "参考图，multipart 上传。"],
      ["prompt", "string", "编辑提示词。"],
      ["model", "string", "可选，默认 gpt-image-2。"],
      ["size", "string", "可选，图片尺寸。"],
      ["quality", "string", "可选，默认 auto。"],
      ["mask", "file", "可选，透明遮罩图。"],
    ],
    output: [
      ["id", "string", "任务 ID。"],
      ["status", "string", "queued / running / success / error。"],
      ["data", "array", "status=success 时返回图片结果。"],
      ["error", "string", "status=error 时返回错误信息。"],
    ],
    example: (baseUrl: string, key: string) => `# 1. 提交图生图任务
curl -X POST ${baseUrl.replace(/\/v1$/, "")}/api/image-tasks/edits \\
  -H "Authorization: Bearer ${key}" \\
  -F "client_task_id=my-edit-001" \\
  -F "model=gpt-image-2" \\
  -F "prompt=改成蓝色调" \\
  -F "image=@./input.png"

# 2. 轮询结果（同文生图任务）
curl ${baseUrl.replace(/\/v1$/, "")}/api/image-tasks?ids=task_yyy \\
  -H "Authorization: Bearer ${key}"`,
    response: `{
  "id": "task_yyy456",
  "status": "running",
  "created_at": "2026-08-09T07:05:00",
  "updated_at": "2026-08-09T07:05:00",
  "size": "1024x1024",
  "model": "gpt-image-2",
  "account_email": "xxx@outlook.com"
}

// 成功后：
{
  "id": "task_yyy456",
  "status": "success",
  "data": [
    {
      "url": "https://chatgpt.com/backend-api/estuary/content?id=file_yyy",
      "revised_prompt": "Blue color scheme, cool tones",
      "expires_at": 1700003600
    }
  ],
  "duration_ms": 52300
}`,
  },
  {
    title: "代理下载上游图片（预览）",
    method: "GET",
    path: "/api/images/proxy-download?url=...",
    icon: FileArchive,
    input: [
      ["url", "query", "上游直链 URL（URL 编码）。后端用账号 token 代理下载，5min 内存缓存。"],
    ],
    output: [
      ["binary", "bytes", "返回 PNG 图片二进制流，可直接用于 <img src>。"],
    ],
    example: (baseUrl: string, key: string) => `# 透传模式下日志页预览用
curl "${baseUrl.replace(/\/v1$/, "")}/api/images/proxy-download?url=https%3A%2F%2Fchatgpt.com%2Fbackend-api%2Festuary%2Fcontent%3Fid%3Dfile_xxx" \\
  -H "Authorization: Bearer ${key}" \\
  -o preview.png`,
    response: `（二进制 PNG 图片流，HTTP 200）
Content-Type: image/png
Cache-Control: private, max-age=300`,
  },
];

const usableModels = [
  "auto", "gpt-5", "gpt-5-1", "gpt-5-2", "gpt-5-3",
  "gpt-5-3-mini", "gpt-5-mini", "gpt-5-4-t-mini", "gpt-5-5",
  "gpt-5-5-mini", "gpt-5-6", "gpt-5-6-mini",
  "gpt-image-2", "research",
];

function ParamTable({ rows }: { rows: ParamRow[] }) {
  return (
    <div className="overflow-hidden rounded-lg border border-stone-200">
      <table className="w-full text-left text-xs">
        <thead className="bg-stone-50 text-stone-500">
          <tr>
            <th className="px-3 py-2 font-medium">参数</th>
            <th className="px-3 py-2 font-medium">类型</th>
            <th className="px-3 py-2 font-medium">说明</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-stone-100 bg-white">
          {rows.map(([name, type, desc]) => (
            <tr key={name}>
              <td className="px-3 py-2 font-mono text-stone-800">{name}</td>
              <td className="px-3 py-2 font-mono text-stone-500">{type}</td>
              <td className="px-3 py-2 text-stone-600">{desc}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ApiDocsCard() {
  const [authKey, setAuthKey] = useState("");
  const [copied, setCopied] = useState(false);
  const serviceBaseUrl =
    webConfig.apiUrl.replace(/\/$/, "") ||
    (typeof window !== "undefined" ? window.location.origin : "");
  const openAIBaseUrl = `${serviceBaseUrl}/v1`;
  const displayKey = authKey || "<当前密钥>";

  useEffect(() => {
    let active = true;
    void getStoredAuthSession().then((session) => {
      if (active) setAuthKey(session?.key || "");
    });
    return () => {
      active = false;
    };
  }, []);

  const fullDocsMarkdown = useMemo(() => {
    let md = `# ChatGPT2API 接口文档\n\n`;
    md += `## 连接信息\n\n`;
    md += `- **服务地址**: \`${serviceBaseUrl}\`\n`;
    md += `- **Base URL**: \`${openAIBaseUrl}\`\n`;
    md += `- **API Key**: \`${displayKey}\`\n`;
    md += `- **鉴权方式**: \`Authorization: Bearer <API Key>\`\n\n`;
    md += `## 可用模型\n\n`;
    md += `\`${usableModels.join("`, `")}\`\n\n`;
    md += `> 也可请求 \`GET /v1/models\` 获取最新模型列表。\n\n`;
    md += `## 接口列表\n\n`;
    for (const doc of docs) {
      md += `### ${doc.title}\n\n`;
      md += `**${doc.method} \`${doc.path}\`**\n\n`;
      md += `#### 输入参数\n\n`;
      md += `| 参数 | 类型 | 说明 |\n|------|------|------|\n`;
      for (const [name, type, desc] of doc.input) {
        md += `| \`${name}\` | ${type} | ${desc} |\n`;
      }
      md += `\n#### 输出参数\n\n`;
      md += `| 参数 | 类型 | 说明 |\n|------|------|------|\n`;
      for (const [name, type, desc] of doc.output) {
        md += `| \`${name}\` | ${type} | ${desc} |\n`;
      }
      md += `\n#### 调用示例\n\n\`\`\`bash\n${doc.example(openAIBaseUrl, displayKey)}\n\`\`\`\n\n`;
      md += `#### 返回示例\n\n\`\`\`json\n${doc.response}\n\`\`\`\n\n`;
    }
    md += `---\n`;
    md += `> 生成时间: ${new Date().toISOString()}\n`;
    md += `> 版本: ${webConfig.appVersion}\n`;
    return md;
  }, [serviceBaseUrl, openAIBaseUrl, displayKey]);

  const handleCopyAll = async () => {
    const ok = await copyText(fullDocsMarkdown);
    if (ok) {
      toast.success("整页文档已复制为 Markdown，可直接粘贴给 AI 分析");
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } else {
      toast.error("复制失败");
    }
  };

  return (
    <Card className="rounded-2xl border-white/80 bg-white/90 shadow-sm">
      <CardContent className="space-y-5 p-6">
        <div>
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2 text-base font-semibold text-stone-900">
              <KeyRound className="size-5 text-stone-500" />
              接口接入说明
            </div>
            <Button
              variant="outline"
              size="sm"
              className="h-8 gap-1.5 rounded-xl border-stone-200 text-xs"
              onClick={() => void handleCopyAll()}
            >
              <Copy className="size-3.5" />
              {copied ? "已复制" : "复制整页文档"}
            </Button>
          </div>
          <p className="mt-1 text-xs leading-6 text-stone-500">
            第三方应用按 OpenAI 兼容接口接入；所有接口统一使用 Bearer Token 鉴权。
          </p>
        </div>

        <div className="grid gap-3 md:grid-cols-2">
          <div className="space-y-1 rounded-xl border border-stone-200 bg-white px-3 py-2">
            <div className="text-xs text-stone-500">服务地址</div>
            <div className="break-all font-mono text-xs text-stone-800">{serviceBaseUrl}</div>
          </div>
          <div className="space-y-1 rounded-xl border border-stone-200 bg-white px-3 py-2">
            <div className="text-xs text-stone-500">Base URL（OpenAI）</div>
            <div className="break-all font-mono text-xs text-stone-800">{openAIBaseUrl}</div>
          </div>
          <div className="space-y-1 rounded-xl border border-stone-200 bg-white px-3 py-2">
            <div className="text-xs text-stone-500">API Key</div>
            <div className="break-all font-mono text-xs text-stone-800">{displayKey}</div>
          </div>
          <div className="space-y-1 rounded-xl border border-stone-200 bg-white px-3 py-2">
            <div className="text-xs text-stone-500">请求头</div>
            <div className="break-all font-mono text-xs text-stone-800">Authorization: Bearer {displayKey}</div>
          </div>
        </div>

        <div className="space-y-2">
          <div className="flex items-center justify-between text-xs font-medium text-stone-600">
            <span>可用模型（也可请求 GET /v1/models 获取最新列表）</span>
            <button
              type="button"
              className="cursor-pointer text-stone-400 hover:text-stone-600"
              onClick={() => {
                void copyText(usableModels.join("\n"));
                toast.success("模型列表已复制");
              }}
              title="点击复制模型列表"
            >
              <Copy className="size-3" />
            </button>
          </div>
          <div className="flex flex-wrap gap-2">
            {usableModels.map((model) => (
              <span
                key={model}
                className="cursor-pointer rounded-md border border-stone-200 bg-white px-2 py-1 font-mono text-xs text-stone-700 transition hover:border-stone-300"
                onClick={() => {
                  void copyText(model);
                  toast.success(`已复制 ${model}`);
                }}
                title={`点击复制 ${model}`}
              >
                {model}
              </span>
            ))}
          </div>
        </div>

        <div className="space-y-3">
          {docs.map((item) => {
            const Icon = item.icon;
            return (
              <details
                key={item.path}
                className="group rounded-xl border border-stone-200 bg-white px-4 py-3"
              >
                <summary className="flex cursor-pointer list-none items-center justify-between gap-3">
                  <span className="flex min-w-0 items-center gap-3">
                    <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-stone-100 text-stone-600">
                      <Icon className="size-4" />
                    </span>
                    <span className="min-w-0">
                      <span className="block text-sm font-semibold text-stone-900">{item.title}</span>
                      <span className="mt-1 block truncate font-mono text-xs text-stone-500">
                        {item.method} {item.path}
                      </span>
                    </span>
                  </span>
                  <ChevronDown className="size-4 shrink-0 text-stone-400 transition group-open:rotate-180" />
                </summary>

                <div className="mt-4 grid gap-4 lg:grid-cols-2">
                  <div className="space-y-2">
                    <h3 className="text-xs font-semibold text-stone-700">输入参数</h3>
                    <ParamTable rows={item.input} />
                  </div>
                  <div className="space-y-2">
                    <h3 className="text-xs font-semibold text-stone-700">输出参数</h3>
                    <ParamTable rows={item.output} />
                  </div>
                  <div className="space-y-2">
                    <h3 className="text-xs font-semibold text-stone-700">调用示例</h3>
                    <pre className="overflow-auto whitespace-pre-wrap break-all rounded-xl bg-stone-950 px-3 py-3 text-xs leading-5 text-stone-100">
                      {item.example(openAIBaseUrl, displayKey)}
                    </pre>
                  </div>
                  <div className="space-y-2">
                    <h3 className="text-xs font-semibold text-stone-700">返回示例</h3>
                    <pre className="overflow-auto whitespace-pre-wrap break-all rounded-xl bg-stone-900 px-3 py-3 text-xs leading-5 text-stone-200">
                      {item.response}
                    </pre>
                  </div>
                </div>
              </details>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}