# Project Constitution — ChatGPT2API

## Core Values

1. **生产级质量优先**: 每一行代码都必须能上生产，不接受"理论上能用"。
2. **调用者体验至上**: API 调用者一次调用就能跑通，参数/返回/认证/错误信息清晰一致。
3. **全链路闭环**: 功能不是"有代码片段"，而是前后端真实打通、可执行、可反馈、可验证。
4. **可维护性不可妥协**: 代码组织清晰、职责明确、文档同步、无伪实现和死代码。
5. **安全是内置属性**: 非功能选项，每个端点都需校验、限流、防注入。

## Technical Principles

### Architecture
- 分层清晰：API → Service → Storage，每层职责单一
- 调度逻辑与业务逻辑分离（AccountService 不混图片处理）
- 熔断/重试/降级策略统一，不散落在各调用点

### Code Quality
- 类型标注全覆盖（Python 3.13+ type hints）
- 函数≤50行，文件≤800行
- 无裸露 `except:`、无可变默认参数、无全局状态突变
- 前后端枚举值/状态码/错误格式对齐

### API Design
- 所有端点需鉴权（除 healthz 等明确白名单）
- 错误响应格式统一：`{error: {message, type, param, code}}`
- 分页/排序/筛选协议一致（limit/offset/total）
- 返回结构稳定性：不轻易删字段、不改类型

### Performance
- 图片走透传（上游直链）避免服务器下行带宽瓶颈
- 日志聚合走 usage_agg 缓存，禁止全量扫日志
- SQL 查询带 LIMIT，无 N+1

### Observability
- Prometheus 指标覆盖：熔断/调度/寿命预测/账号池
- 结构化日志含 request_id 全链路追踪
- healthz/ready 探针存活检测

## Decision Framework

1. 是否影响现有调用方？→ 向后兼容优先
2. 是否经过测试验证？→ 单测+集成+E2E 三级覆盖
3. 文档是否同步？→ README/CHANGELOG/API 文档同步更新
4. 降级路径是否明确？→ 外部依赖不可用时的系统行为