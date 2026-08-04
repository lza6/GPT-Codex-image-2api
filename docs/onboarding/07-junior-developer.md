# 07 · 初级开发者入门指南（零基础版）

> 受众：熟悉 Python / JavaScript 基础语法，但没写过 FastAPI 后端、没碰过 Next.js 前端、对"逆向封装""账号池"这类词陌生的人。
> 目标：**看懂这个项目是干嘛的 → 把环境跑起来 → 读懂一次真实请求的完整旅程 → 能独立完成三个小任务 → 会跑测试、会排查新手坑。**
> 生成日期：2026-08-05 · 当前版本 **2.3.0** · 配套高级版：[01-architecture.md](01-architecture.md)（架构细节）[03-setup.md](03-setup.md)（环境变量全表）[05-debugging.md](05-debugging.md)（历史故障档案）

---

## 0. 先弄明白：这个项目到底是什么？

**一句话**：它把「ChatGPT 官网的画图能力」打包成了一个**长得像 OpenAI 官方 API** 的服务，让你用任何支持 OpenAI 接口的工具（Cherry Studio、SDK、curl）就能调用 ChatGPT 画图，而不用自己登官网。

**打个比方**：OpenAI 官方 API 是「官方餐厅」——正规、贵、要排队。ChatGPT 官网是「自己家厨房」——你有几个账号（有几口锅），但是要通过浏览器才能用。这个项目干的事就是：**在你自己家厨房外面开了个官方餐厅样式的窗口**。你在窗口点菜（发 OpenAI 风格请求），它在里面挑一口空闲的锅（从账号池挑一个 ChatGPT 账号），帮你把菜做出来（调官网能力），再把菜端给你（返回 OpenAI 风格响应）。

因为它**绕过了官方 API 收费**，只花你已有的 ChatGPT 会员/额度，所以这是一个**逆向研究项目**，仅供内部自用，不做商业/批量/滥用——这是项目的三条红线之一。

**技术栈一句话版**：

| 名词 | 大白话 |
|------|--------|
| Python 3.13 + FastAPI | 写后端服务（接收 HTTP 请求、返回响应）的框架 |
| Next.js 16 + React 19 | 写前端网页（登录、看板、画图页面）的框架 |
| curl-cffi | 一个"伪装成浏览器"发 HTTP 请求的库（上游只认浏览器） |
| JSON / SQLite / PostgreSQL | 三种可选的数据存储方式 |
| uv | Python 依赖管理器（相当于 npm 之于 Node） |

**系统长这样**：

```
你 (浏览器 / OpenAI 客户端 / curl)
   │  HTTP 请求 + Bearer 密钥
   ▼
┌────────────────────────────── 后端 :23456 ──────────────────────────────┐
│  api/          网关层：收请求、校验密钥、组织参数                          │
│  services/     业务层：选账号、防熔断、管任务                              │
│  protocol/     协议层：把「OpenAI 格式」翻译成「ChatGPT 官网格式」          │
└──────────────────────────────┬──────────────────────────────────────────┘
                               ▼  curl-cffi（伪装浏览器）
                     ChatGPT 官网上游（真正的画图能力）
```

**生产模式下，前端网页也是后端托管的**：`web/` 构建出来的静态文件放在 `web_dist/`，由后端 23456 端口直接提供（见 `api/app.py` 的 `serve_web` 兜底路由）。所以**日常开发你只需要关心一个端口：23456**。只有改前端代码时才需要开 3000 端口的 dev 服务器。

---

## 1. 术语表（先读这个，后面全靠它）

> 原则：**同一个词在不同上下文可能指不同东西**，下面把最容易混的都标出来了。

| 术语 | 展开 / 含义 |
|------|-------------|
| API | 应用程序接口：别人按照你规定的格式发请求，你返回数据。这里指 HTTP 接口 |
| OpenAI 兼容 | 请求/响应格式与 OpenAI 官方 API 一致，任何 OpenAI 客户端开箱即用 |
| **Token（第一大坑）** | 在本文档至少有三重意思：① **auth-key**：调用本服务的密钥（`Authorization: Bearer xxx`）；② **access_token**：ChatGPT 账号的登录凭证（账号池里每个账号一个）；③ **usage token**：计费单位（图片生成输入/输出的 token 数）。看代码时先判断是哪个 |
| 账号池 | 一组 ChatGPT 账号的 access_token 集合，存在 `data/accounts.json` 等存储里 |
| 调度 / Scheduler | 决定「这次请求用哪个账号」的逻辑，见 `services/account_service.py` |
| 健康档位 | 调度给每个账号打分：`healthy`（健康）/ `warm`（还行）/ `risky`（危险） |
| 熔断 / Circuit Breaker | 一个账号连续失败太多次就暂时让它"冷静"（OPEN 状态），过段时间再试（HALF_OPEN），防止一个坏账号拖垮整个服务 |
| SSE | Server-Sent Events：服务端往客户端**单向推送**文本的机制（聊天流式输出的底层） |
| Stream | 流式：响应不是一个完整 JSON，而是一块块地发过来 |
| b64_json | 图片用 Base64 编码成的字符串，这样图片可以直接放进 JSON 里传输 |
| ORM | 对象关系映射。用 `SQLAlchemy` 让你**写 Python 对象而不是 SQL** 来操作数据库，防 SQL 注入 |
| Worker | 进程。`workers=4` 表示同时跑 4 个进程处理请求 |
| Prometheus | 监控指标系统，`/metrics` 端点输出机器可读的运行数据 |
| TestClient | FastAPI 自带的测试工具：不开真实端口，直接在代码里模拟发请求 |
| webpack | 前端打包工具。**本项目前端构建必须用它**（中文路径下 Turbopack 会崩，历史坑） |
| SSRF | 服务端请求伪造：一种安全漏洞——诱导服务器去访问不该访问的内部地址 |
| 逆向 / Reverse | 不靠官方文档，靠分析网络请求来搞清楚一个系统怎么工作 |

---

## 2. 动手前先读这 5 个文件（按顺序）

> 不是全读，是按顺序"扫"一遍，建立地图感。**每一篇都带着下面的问题读**：入口在哪？数据往哪流？改哪里会出事？

| 顺序 | 文件 | 读它解决什么问题 | 花多长时间 |
|------|------|------------------|-----------|
| 1 | `api/app.py` | 整个服务是怎么"组装"起来的（路由 + 中间件） | 10 分钟 |
| 2 | `api/ai.py` | OpenAI 兼容端点长什么样（对外的大门） | 10 分钟 |
| 3 | `services/account_service.py` 的 `get_available_access_token`（约 1129 行起） | 最核心的"选账号"逻辑 | 10 分钟 |
| 4 | `services/protocol/openai_v1_image_generations.py`（整个文件只有 51 行） | 一个最简"协议转换"长什么样 | 5 分钟 |
| 5 | `web/src/constants/common-env.ts` | 前端怎么知道后端在哪（dev / 生产区别） | 2 分钟 |

**为什么是这 5 个**：它们分别代表了「网关怎么装配 → 大门长啥样 → 核心业务 → 最简协议层 → 前后端连接方式」。看完这 5 个，你已经知道「改哪里会出事」的八成答案了。

**⚠️ 改代码前必读**：如果你要改任何东西，先读 `.claude/skills/chatgpt2api-workflow/SKILL.md`——里面有完整的开发规范、验收清单、历史 bug 警示（哪些坑绝不能重犯）。**这条规则适用于本项目所有改动。**

---

## 3. 本地环境搭建（逐步版）

> 每条命令后面括号里是"这条在干嘛"，别跳过。

### 3.1 前置要求

| 依赖 | 要求 | 怎么检查 |
|------|------|---------|
| Python | ≥ 3.13（代码用了新语法） | `python --version` |
| 项目虚拟环境 `.venv` | 已存在（仓库自带创建流程） | 看项目根目录有没有 `.venv/` 文件夹 |
| Node.js | ≥ 20（只有改前端才需要） | `node --version` |

> 说明：这个项目**不依赖全局 uv 或全局 Python**。如果根目录已有 `.venv/`，直接用里面的 Python 就行（下面命令都这么写）。如果是全新机器，用 `uv sync` 生成 `.venv`（`pyproject.toml` 已配好阿里云镜像源，下载快）。

### 3.2 后端（必做，约 3 分钟）

```bash
# 1. 进到项目根目录
cd chatgpt2api

# 2. 确认虚拟环境可用（能打印出版本号就行）
.venv/Scripts/python.exe --version

# 3. 准备配置文件
#    config.json 不会进 git，首次需要自己建。最小配置只填一个密钥：
#    在项目根目录新建 config.json，内容写：
#    { "auth-key": "随便填一个 ≥12 位的字符串" }
#    完整字段参考 config.example.json（仓库里有示例，可复制改名）。

# 4. 跑测试验证环境（默认不联网，安全）
.venv/Scripts/python.exe -m pytest test/ -q
# 期望输出：一堆 . 和 passed，没有 failed / error
```

### 3.3 启动后端

```bash
# 方式一：命令行（推荐调试用）
.venv/Scripts/python.exe main.py
# → 打开浏览器访问 http://localhost:23456（前端页面）
# → http://localhost:23456/docs （Swagger 接口文档，最好用的调试工具）

# 方式二：Windows 一键脚本（日常用）
# 双击根目录「启动chatgpt2api.bat」—— 自动检测环境、崩溃自动重启。
# 停止用「停止chatgpt2api.bat」。
# ⚠️ 千万别用编辑器重存这两个 .bat：必须保持 GBK 编码 + CRLF + 无 BOM。
```

### 3.4 验证搭好了（全绿才算成功）

```bash
# 密钥验证：用 curl 模拟一次最轻的请求（把 xxx 换成你的 auth-key）
curl http://localhost:23456/v1/models -H "Authorization: Bearer xxx"
# 期望：返回 200 和一个 JSON 列表

# 服务健康
curl "http://localhost:23456/metrics?token=xxx"
# 期望：输出 Prometheus 文本（很多带 # 开头的注释行）。2.3.0 起 /metrics 要鉴权，
# 裸 curl 返回 401 是【正确】行为，别当成 bug
```

### 3.5 前端（仅当任务涉及 `web/` 目录）

```bash
cd web
npm install        # 装前端依赖（第一次比较久）
npm run dev        # 启动 dev 服务器 → http://localhost:3000
```

**dev 模式下前端如何连后端**：看 `web/src/constants/common-env.ts`——开发环境 `apiUrl` 固定为 `http://127.0.0.1:23456`，生产环境为空字符串（走同源，由后端托管）。所以改前端时要**同时开着后端 23456 和前端 3000**。

> 构建前端用 `npm run build`（**固定带 `--webpack`**，中文路径下 Turbopack 会崩，别改回 `next build` 默认参数）。

---

## 4. 读懂一次真实请求的完整旅程（文生图）

> 这一节是全文核心。我们用一次「文生图」请求，从你按下回车到拿到图片，逐层走一遍。**每层都贴了真实代码，边看边对照文件。**

### 4.1 第 0 层：客户端发起

你（或任何 OpenAI 客户端）发出这样一次请求：

```bash
curl http://localhost:23456/v1/images/generations \
  -H "Authorization: Bearer 你的auth-key" \
  -d '{"model":"gpt-image-2","prompt":"一只戴帽子的猫","n":1}'
```

### 4.2 第 1 层：网关收单（`api/ai.py:91`）

```python
@router.post("/v1/images/generations")
async def generate_images(body: ImageGenerationRequest, request: Request, authorization=None):
    identity = require_identity(authorization)              # ① 校验密钥
    payload = body.model_dump(mode="python")                # ② 把请求体转成 dict
    payload["base_url"] = resolve_image_base_url(request)   # ③ 记下图片 URL 前缀
    call = LoggedCall(identity, "/v1/images/generations", body.model, "文生图", request_text=body.prompt)
    await filter_or_log(call, body.prompt)                  # ④ 内容审核（敏感词）
    return await call.run(openai_v1_image_generations.handle, payload)  # ⑤ 交给协议层
```

四个动作，每个都是关键点：
- **① 鉴权**：密钥不对直接 401。实现见 `api/support.py:31`——把 `Authorization: Bearer xxx` 里的 xxx 取出来，先比对配置里的 `auth-key`（管理员密钥），再用 OAuth 身份校验。
- **④ 内容审核**：`services/content_filter.py` 检查 prompt 是否含敏感词，违规直接拒绝。**这是第一道安全防线。**
- **⑤ 交给协议层**：网关层自己不干活，只做"收单 + 校验 + 转发"，真正的逻辑在 `services/protocol/`。
- **`LoggedCall.run`**：它是日志包装器（`services/log_service.py:366`），负责把这次调用的成败、耗时记进日志，**异常也被它捕获转成标准错误格式**——所以你在协议层 `raise ImageGenerationError(...)` 就行，不用自己拼 HTTP 错误响应。

### 4.3 第 2 层：协议层组装（`services/protocol/openai_v1_image_generations.py`，全文 51 行）

```python
def handle(body: dict[str, Any]) -> dict[str, Any] | Iterator[dict[str, Any]]:
    prompt = str(body.get("prompt") or "").strip()
    if not prompt:                                  # 参数校验：prompt 必填
        raise ImageGenerationError("prompt is required", status_code=400, ...)
    outputs = stream_image_outputs_with_pool(ConversationRequest(
        prompt=prompt, model=model, n=n, size=size, quality=quality,
        response_format=response_format, base_url=base_url, message_as_error=True,
    ))
    if body.get("stream"):
        return stream_image_chunks(outputs)         # 流式：逐块返回
    result = collect_image_outputs(outputs)         # 非流式：攒齐一次返回
    result["usage"] = image_usage(...)              # 计算消耗的 token 数
    return result
```

**这一层是"翻译官"**：把 OpenAI 格式的请求参数（prompt、model、n、size…）打包成一个 `ConversationRequest` 对象，交给 `conversation.py` 去真正干活。`stream_image_outputs_with_pool` 这个名字的 `with_pool` 暗示了下一步——它会去账号池取账号。

### 4.4 第 3 层：选账号 + 熔断（`services/account_service.py:1129`，调度核心）

```python
def get_available_access_token(self, ...) -> str:
    max_attempts = 20                      # 最多试 20 个账号，防死循环
    for _attempt in range(max_attempts):
        access_token = self._acquire_next_candidate_token(...)   # ① 按调度算法挑一个候选
        breaker = circuit_breaker_registry.get(access_token)
        if not breaker.allow_request():     # ② 熔断中的账号直接跳过
            continue
        account = self.fetch_remote_info(access_token, ...)      # ③ 远程验证账号/配额
        if (self._is_image_account_available(account) and ...):  # ④ 真正可用才用
            breaker.record_success()        # ⑤ 可用 → 记成功（位置很关键，历史坑）
            return access_token
        breaker.record_failure()            # ⑥ 不可用 → 记失败
    raise RuntimeError("no available image quota ...")
```

调度器做的事，一句话：**「挑一个 → 熔断检查 → 远程确认 → 可用就用，不可用换下一个」**。最多试 20 个，全都不行就报"没有可用配额"。

两个注释标了**历史坑**，改这里要特别小心：
- `record_success()` 必须在确认账号真的可用之后调用。曾经有人把它放在返回之前过早调用，导致"坏账号被记成成功"被当成好账号用。
- 这个循环里的远程验证 `fetch_remote_info` 每次都要访问上游，所以它**很贵**——这也是为什么有会话复用（`session_pool.py`）来省连接。

### 4.5 第 4 层：真正发上游请求

`ConversationRequest` 最终走到 `services/openai_backend_api.py`，用 **curl-cffi**（伪装浏览器 TLS 指纹）把请求发给 ChatGPT 官网，拿到图片数据。返回的图片通常是 Base64 字符串，协议层把它放进 `data` 数组的 `b64_json` 字段，你收到的是**标准的 OpenAI 图片响应格式**：

```json
{
  "created": 1234567890,
  "data": [ { "b64_json": "iVBORw0KGgo..." } ],
  "usage": { "input_text_tokens": 12, "output_tokens": 1024 }
}
```

### 4.6 旅程回顾（一分钟版）

```
你发 curl
  → api/ai.py         校验密钥 + 内容审核 + 记日志
  → protocol/handle   参数校验，打包成上游请求
  → account_service   挑账号（熔断跳过坏号）
  → openai_backend    伪装浏览器，请求官网
  → 图片回来了，层层返回
```

**任何功能都跑在这条主链路上**。聊天的 `/v1/chat/completions`、Anthropic 协议的 `/v1/messages`、搜索的 `/v1/search` 都是**同一个调度/熔断/会话复用框架**，只是协议转换的文件不同（都在 `services/protocol/` 里）。

---

## 5. 三个任务演练（从简到难）

> 原则：**每次改动前先读 `.claude/skills/chatgpt2api-workflow/SKILL.md`**，改完跑验收。这里给每个任务的"最小闭环"，完整门禁（五道防线等）在 SKILL.md。

### 任务 A：改前端页面上的一个文字（最简单，练手感）

**场景**：把登录页的标题从「欢迎使用」改成「ChatGPT2API 内部工具」。

1. 找到登录页文件：`web/src/app/login/page.tsx`（前端页面都在 `web/src/app/` 下，按功能分目录）
2. 用编辑器搜索「欢迎使用」，改成新文案
3. 验证：
   ```bash
   cd web && npm run dev        # 打开 http://localhost:3000/login 看效果
   cd web && npm run build      # 确认能构建（webpack，中文路径必须）
   ```

**要点**：纯文案改动是"安全区"，直接 PR 即可。但**如果改的是按钮/开关/菜单**，必须确认点击后有真实的后端调用——项目历史上有过"界面上有、流程走不通"的假功能被契约守卫抓出来的教训。

### 任务 B：新增一个配置项（6 步，理解"配置从哪来到哪去"）

**场景**：加一个 `image_poll_interval_secs`（图片轮询间隔）之类的配置。SKILL.md 规定**必须 6 步全做**：

| 步 | 文件 | 干嘛 |
|----|------|------|
| 1 | `config.json` | 加默认值（仓库的 `config.example.json` 同步加） |
| 2 | `services/config.py` | 加一个 `@property` 读取（含环境变量覆盖 `CHATGPT2API_*`） |
| 3 | `services/config.py` | 在 `get()` 方法里暴露该配置 |
| 4 | `services/config.py` | 在 `_validate_schema` 里加类型校验（防手抖填错类型启动失败） |
| 5 | `web/src/lib/api.ts` | 在 `SettingsConfig` 类型里加字段 |
| 6 | `web/src/app/settings/store.ts` | 在 `normalizeConfig` 加默认值 + `config-card.tsx` 加 UI |

**为什么是 6 步**：配置横跨「后端读取 → schema 校验 → 前端类型 → 设置页 UI」四层。**只做 1-2 步就会断链**（前端调了后端没有的字段 = 契约守卫会报）。这也是理解"前后端契约"最直观的一次练习——字段名必须两边完全一致。

### 任务 C：新增一个 API 端点（理解后端结构）

**场景**：加一个 `/v1/ping`，返回 `{"pong": true}` 供健康检查用。

1. 新建 `api/ping.py`，写一个 `create_router()`：
   ```python
   from fastapi import APIRouter, Header
   from api.support import require_identity

   def create_router() -> APIRouter:
       router = APIRouter()

       @router.get("/v1/ping")
       async def ping(authorization: str | None = Header(default=None)):
           require_identity(authorization)          # 鉴权（大多数端点都要）
           return {"pong": True}

       return router
   ```
2. 在 `api/app.py` 里注册：
   ```python
   from api import ping          # 顶部 import
   app.include_router(ping.create_router())   # 和其他 router 放一起
   ```
3. 验证：
   ```bash
   .venv/Scripts/python.exe -c "from api.app import create_app; create_app()"   # 能建起来
   curl http://localhost:23456/v1/ping -H "Authorization: Bearer xxx"           # 返回 200
   ```
4. **给新端点加测试**（见下一节），因为 SKILL.md 规定"后端实现 ≠ 已闭环"，必须有测试和（如适用）前端消费证据。

**要点**：
- 端点文件放 `api/` 下，实现 `create_router()` 模式（项目内所有路由都这样）
- 同步调用（不是 async 的函数）用 `run_in_threadpool` 包一下，别阻塞事件循环
- **新增端点 = 必须加进契约守卫的 SNAPSHOT_ENDPOINTS**（见 `scripts/contract_guard.py`），否则契约检测不覆盖它

---

## 6. 测试入门

### 6.1 怎么跑

```bash
# 跑全部测试（默认排除 live/redis 标记，不会联网、不会烧账号配额）
.venv/Scripts/python.exe -m pytest test/ -q

# 只跑一个文件
.venv/Scripts/python.exe -m pytest test/test_config.py -q

# 带详细信息（看每个用例名字）
.venv/Scripts/python.exe -m pytest test/ -v
```

### 6.2 测试文件长什么样

测试全在 `test/` 目录，文件名 `test_*.py`。用的是 Python 标准库 `unittest`。看 `test/test_config.py` 的骨架：

```python
class ConfigLoadingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # 测试前的准备：创建临时 config、导入被测模块
        ...
    def test_load_settings_ignores_directory_config_path(self) -> None:
        # 一个用例 = 一个 test_ 开头的方法
        # 命名 = 你断言的行为
        ...
```

测试的三大类型（项目约定）：

| 标记 | 含义 | 是否默认跑 |
|------|------|-----------|
| `@pytest.mark.unit` | 纯单元测试（不联网） | ✅ 是 |
| `@pytest.mark.live` | 需要真实上游账号（会烧配额） | ❌ 否（`-m live` 才跑，别乱跑） |
| `@pytest.mark.redis` | 需要 Redis | ❌ 否 |

### 6.3 新手最容易犯的测试错误

- **跑 `-m live` 烧了配额**：live 测试会真实调用上游画图，耗账号额度。**默认不跑是对的，别手动加 `-m live` 除非你知道在干嘛。**
- **改代码后忘记跑测试**：改完任何东西，至少跑一遍相关测试文件 + `create_app()` 能建起来。
- **测试里改环境变量污染其他测试**：`test/conftest.py` 里已经用了 autouse fixture 隔离 `CHATGPT2API_AUTH_KEY`。**你自己的测试里别用 `os.environ.setdefault` 改 auth-key**——这是历史坑（环境污染击穿测试）。

---

## 7. 新手调试速查（按症状找）

> 更全的历史故障档案在 [05-debugging.md](05-debugging.md)。

| 症状 | 原因 | 解决 |
|------|------|------|
| 启动报错，提示 config.json 某行号 | config 有字段填错/类型不对（schema 校验） | 按报错行号改 config.json；多半是字段名拼错 |
| 所有请求返回 401 | auth-key 没配、或 Bearer 头写错 | 确认 config.json 有 `auth-key`；请求头 `Authorization: Bearer <auth-key>` |
| 启动警告"workers 回退到 1" | 存储是 JSON 却配了 `workers>1` | 多进程必须用 SQLite/Postgres；或接受单 worker。**这是数据安全兜底，别强行关掉** |
| 端口 23456 被占用 | 上次的服务没停 | 跑 `停止chatgpt2api.bat`，或 `netstat -ano \| findstr :23456` 找到 PID 杀掉 |
| 前端连不上后端（dev） | 后端没开 | 前端 3000 依赖后端 23456，先 `python main.py` |
| 前端构建失败（中文路径） | 用了 Turbopack | 构建必须 `npm run build`（已配 `--webpack`），别改成默认 |
| 改了后端字段，前端报错 | 前后端契约断了 | 跑 `scripts/contract_probe.py` + `test/test_contracts.py` 双验证 |
| 图片生成一直报"没有可用配额" | 账号池的号配额用尽 / 全部被熔断 | 看 `api/accounts.py` 的账号状态、熔断状态（看板有展示） |
| 代码改了没生效 | 多进程 Worker 没重启 | 重启服务（bat 自动重启；命令行手动 Ctrl+C 重跑） |

### 调试辅助工具

- **Swagger**：`http://localhost:23456/docs` —— 每个端点的参数说明 + 在线调试，新手最该用的工具。
- **日志**：`http://localhost:23456` 前端「日志」页面可搜索；命令行看 stdout 也行。
- **看板**：`http://localhost:23456` 的「运维看板」——账号健康、调度、熔断、延迟一目了然，排查调度问题先看它。
- **X-Request-ID**：每个响应头都带一个 16 位请求 ID（`api/app.py` 中间件注入），把报错的请求 ID 贴给老手，对方能直接在日志里定位到那次调用。

---

## 8. 学习资源与进阶路径

### 项目内必读（按顺序）

| 顺序 | 文档 | 适合什么时候 |
|------|------|-------------|
| 1 | [01-architecture.md](01-architecture.md) | 想深入架构（高级版，读完本文档再看最顺） |
| 2 | [03-setup.md](03-setup.md) | 需要环境变量全表 / Docker 部署时 |
| 3 | [04-task-runbooks.md](04-task-runbooks.md) | 要加存储后端 / 多 Worker / 部署时 |
| 4 | [05-debugging.md](05-debugging.md) | 遇到本文档没覆盖的报错 |
| 5 | `docs/api/` | 对外 API 契约（OpenAPI 3.0 + 错误码表） |
| 6 | `.claude/skills/chatgpt2api-workflow/SKILL.md` | **改任何代码前必读** |

### 外部学习资源（看不懂的技术名词去这学）

| 想学 | 资源 |
|------|------|
| FastAPI 入门 | 官方文档 [fastapi.tiangolo.com](https://fastapi.tiangolo.com/tutorial/)（有中文） |
| HTTP 基础（请求/响应/状态码） | MDN：[HTTP 概述](https://developer.mozilla.org/zh-CN/docs/Web/HTTP/Overview) |
| Next.js / React | [nextjs.org/learn](https://nextjs.org/learn)（官方交互式教程） |
| Python unittest | [Python 官方 unittest 文档](https://docs.python.org/zh-cn/3/library/unittest.html) |
| OpenAI API 格式 | [platform.openai.com/docs](https://platform.openai.com/docs)（本项目模仿的就是它） |

### 进阶路径建议

1. **第 1 周**：能跑起来 + 会发请求 + 能读懂 `api/ai.py` 任一端点 + 能完成"任务 A"
2. **第 2 周**：能完成"任务 B/C" + 会给新逻辑写测试 + 理解调度的三档打分
3. **第 3 周**：通读 `services/account_service.py` 和 `services/circuit_breaker.py`（本项目最难也是最重要的两个模块）+ 能解释熔断状态机
4. **出师**：能独立排查线上问题（看板 + 日志 + 契约守卫定位）+ 改协议层字段敢跑双验证

---

*最后更新：2026-08-05 · 对应版本 2.3.0。若项目版本变化、本文档与代码不符，先更新文档再改代码（项目约定）。*
