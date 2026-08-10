# 事件总线系统设计（v2.24.0 增强版）

## 问题

模块间耦合通过直接函数调用：`circuit_breaker.py` 内联调用 `alert_service.send_alert()` 和 `prometheus_metrics.record_circuit_breaker_transition()`，`account_service.py` 内联调用 `send_alert()`，`backup_service.py` 同样。新增通知方必须修改被调用方代码，难以扩展和追踪。

## 方案

增强版事件总线（基于 asyncio + threading，无外部依赖），同步/异步双模式发布 + 异步消费者模式 + 事件类型枚举 + 事件统计。

## 架构

```
发布方                          EventBus                         订阅方
circuit_breaker ──publish──→  ┌──────────────┐  ──sync──→  alert_service
account_service  ──publish──→  │ sync_handlers │  ──sync──→  prometheus_metrics
backup_service   ──publish──→  │ async_handlers│  ──async──→ log_service
config           ──publish──→  │ consumer_queue│  ──async──→ (其他模块)
                               └──────┬───────┘
                                       │
                                       ▼
                                 data/event_dead_letter.jsonl
```

## 组件

### 1. EventType 枚举 (`services/event_bus.py`)

26 个事件类型，分 7 类：

| 分类 | 事件类型 | 发布方 |
|------|---------|--------|
| 账号 | account.created/updated/deleted/expired/invalid/recovered/quota_exhausted/quota_low/blocked | account_service |
| 调度 | scheduler.picked/failed/no_account | provider_scheduler |
| 熔断 | circuit.open/half_open/closed | circuit_breaker |
| 系统 | system.memory_high/disk_low/startup/shutdown | system |
| 备份 | backup.failure | backup_service |
| 配置 | config.changed | config |
| 代理 | proxy.failed/recovered | proxy_pool |
| Provider | provider.health_changed | provider_scheduler |
| 图片 | image.task_completed | image_task_service |
| 会话 | session.degraded | session_pool |

### 2. Event 增强字段

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| type | str | - | 事件类型 |
| data | dict | {} | 事件载荷 |
| id | str | uuid hex[:16] | 事件唯一 ID |
| timestamp | float | time.time() | 事件时间戳 |
| source | str | "system" | 事件来源标识 |
| severity | str | "info" | 严重级别（debug/info/warning/error/critical） |

### 3. EventBus 核心

#### 订阅

- `subscribe(event_type, sync_handler, async_handler)` — 注册特定事件类型
- `subscribe_all(sync_handler, async_handler)` — 通配符订阅所有事件类型
- `unsubscribe(event_type, handler)` — 取消注册

#### 发布（同步模式，向后兼容）

- `publish(event)` — 同步发布（sync handler 当前线程执行，async handler 调度到事件循环）
- `publish_async_direct(event)` — 异步发布（await 所有 handler）

#### 发布（异步消费者模式，新增）

- `publish_async(event)` — 异步发布（入队到消费者队列，后台 consumer 处理）
- `publish_sync(event)` — 同步上下文入队到消费者队列（无事件循环时回退到同步发布）
- `start_consumer()` — 启动消费者后台协程
- `stop_consumer()` — 停止消费者

#### 死信队列

- handler 抛异常时写入 `data/event_dead_letter.jsonl`
- 死信记录包含：事件详情、handler 名称、错误信息、写入时间

#### 事件统计（新增）

- `get_event_stats()` — 返回统计快照
- 统计项：按事件类型发布数、按 severity 分布、handler 调用次数/平均耗时、死信计数、消费者处理数、消费者队列深度、uptime

### 4. Prometheus 指标（新增）

| 指标 | 类型 | Label | 说明 |
|------|------|-------|------|
| c2api_events_published_total | Counter | type, severity | 事件发布计数 |
| c2api_events_consumer_processed_total | Counter | type | 消费者处理计数 |
| c2api_events_dead_letter_total | Counter | - | 死信事件计数 |
| c2api_events_handler_duration_seconds | Histogram | type, handler | handler 处理耗时 |

### 5. 订阅关系

| 事件 | 订阅方 | 模式 |
|------|--------|------|
| 所有事件 | event_metric_wrapper | async（subscribe_all） |
| circuit.open | alert_service.send_alert | sync |
| circuit.open | prometheus_metrics.record_circuit_breaker_transition | sync |
| circuit.half_open | prometheus_metrics.record_circuit_breaker_transition | sync |
| circuit.closed | alert_service.send_alert | sync |
| circuit.closed | prometheus_metrics.record_circuit_breaker_transition | sync |
| account.invalid | alert_service.send_alert | sync |
| account.recovered | alert_service.send_alert | sync |
| account.quota_exhausted | alert_service.send_alert | sync |
| account.blocked | alert_service.send_alert | sync |
| account.quota_low | alert_service.send_alert | sync |
| backup.failure | alert_service.send_alert | sync |
| session.degraded | alert_service.send_alert | sync |
| image.task_completed | log_service + image_metrics | sync |

### 6. 初始化

`services/event_bus_init.py` 集中注册所有订阅关系，在 `api/app.py` lifespan 中调用。

`api/app.py` lifespan 启动消费者后台协程：
```python
event_bus_consumer_task = asyncio.ensure_future(event_bus.start_consumer())
```

## 向后兼容

- 所有现有字符串常量保留为 `EventType.value` 的别名
- `EventBus` 类名不变（不引入 EventBusV2 新类名）
- `publish()` 方法行为不变（直接调用 handler）
- 新增 `publish_async()` 入队消费者模式，现有 `publish_async_direct()` 保持原行为
- 因 `event_bus` 是全局单例，所有现有发布方代码无需修改

## 不做的

- 事件溯源 / 重放（重启丢失可接受，死信队列保留失败记录）
- 优先级队列（按事件类型顺序执行即可）
- 分布式事件总线（单进程即可，多 Worker 各走各的）
- 将服务调用（cpa_service→account_service、openai_backend_api→account_service）改为事件——那些是 API 调用而非通知