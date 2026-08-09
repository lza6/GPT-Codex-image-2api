# 事件总线系统设计

## 问题

模块间耦合通过直接函数调用：`circuit_breaker.py` 内联调用 `alert_service.send_alert()` 和 `prometheus_metrics.record_circuit_breaker_transition()`，`account_service.py` 内联调用 `send_alert()`，`backup_service.py` 同样。新增通知方必须修改被调用方代码，难以扩展和追踪。

## 方案

轻量级事件总线（基于 asyncio + threading，无外部依赖），同步/异步双模式发布，死信队列文件持久化。

## 架构

```
发布方                          EventBus                         订阅方
circuit_breaker ──publish──→  ┌─────────────┐  ──sync──→  alert_service
account_service  ──publish──→  │  sync_handlers│  ──sync──→  prometheus_metrics
backup_service   ──publish──→  │  async_handlers              log_service
config           ──publish──→  └─────────────┘  ──async──→  (其他模块)
                                  │
                                  ▼
                            data/event_dead_letter.jsonl
```

## 组件

### 1. 事件定义 (`services/event_bus.py`)

| 事件类型 | data 字段 | 发布方 |
|---------|----------|--------|
| `account.invalid` | token_suffix, reason | account_service |
| `account.recovered` | token_suffix | account_service |
| `account.quota_exhausted` | tried_tokens, plan_type, source_type | account_service |
| `circuit.open` | token_suffix, failure_threshold, from_state | circuit_breaker |
| `circuit.half_open` | token_suffix | circuit_breaker |
| `circuit.closed` | token_suffix | circuit_breaker |
| `backup.failure` | error, trigger | backup_service |
| `config.changed` | - | config |

### 2. EventBus 核心

- `subscribe(event_type, sync_handler, async_handler)` — 注册
- `publish(event)` — 同步发布（sync handler 当前线程执行，async handler 调度到事件循环）
- `publish_async(event)` — 异步发布（await 所有 handler）
- `unsubscribe(event_type, handler)` — 取消注册
- 死信队列：handler 抛异常时写入 `data/event_dead_letter.jsonl`

### 3. 订阅关系

| 事件 | 订阅方 | 模式 |
|------|--------|------|
| circuit.open | alert_service.send_alert | sync |
| circuit.open | prometheus_metrics.record_circuit_breaker_transition | sync |
| circuit.half_open | prometheus_metrics.record_circuit_breaker_transition | sync |
| circuit.closed | alert_service.send_alert | sync |
| circuit.closed | prometheus_metrics.record_circuit_breaker_transition | sync |
| account.invalid | alert_service.send_alert | sync |
| account.quota_exhausted | alert_service.send_alert | sync |
| backup.failure | alert_service.send_alert | sync |

### 4. 初始化

`services/event_bus_init.py` 集中注册所有订阅关系，在 `main.py` 启动时调用。

## 不做的

- 事件溯源 / 重放（重启丢失可接受，死信队列保留失败记录）
- 优先级队列（按事件类型顺序执行即可）
- 分布式事件总线（单进程即可，多 Worker 各走各的）
- 将服务调用（cpa_service→account_service、openai_backend_api→account_service）改为事件——那些是 API 调用而非通知