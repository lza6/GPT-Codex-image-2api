# ChatGPT2API 工作流状态 — 第十九轮（8.2 多 Provider 精细调度）

> 最后更新：2026-08-10
> 模式：v2.16.0 多 Provider 精细调度 —— 配额隔离 + 权重分配 + 失败隔离 + 看板状态卡片
> 基线：v2.15.0

## 本轮完成清单

| 编号 | 事项 | 状态 | 证据 |
|------|------|------|------|
| A | 配置项 `provider_weights` + `provider_rate_limit_rpm` | ✅ | `services/config.py` 新增属性+`_DICT_FIELDS`校验+`get()`序列化 |
| B | Provider 级 rate limiter（滑动窗口，独立计数） | ✅ | `services/provider_scheduler.py` `_check_provider_rate_limit`/`_provider_rate_remaining`，6 单测 |
| C | Provider 权重调度（配置化比率） | ✅ | `provider_scheduler._pick_provider_by_weight`/`_get_weighted_providers`，6 单测 |
| D | Provider 熔断器（阈值 3 次/60s 冷却/成功清零） | ✅ | `provider_scheduler._record_provider_failure`/`_record_provider_success`/`_provider_allow_request`，6 单测 |
| E | `get_text_access_token` 接入权重调度+配额+熔断+fallback | ✅ | `services/account_service.py` 配额耗尽/熔断自动转向其他 provider |
| F | `get_available_access_token` 接入权重选取+配额/熔断检查 | ✅ | `services/account_service.py` 图片生图 token 选取接入 |
| G | 前端类型+看板 provider 卡片展示新字段 | ✅ | `web/src/lib/api.ts` 类型扩展 + `dashboard/page.tsx` 展示配额/权重/熔断 |
| H | 验证全绿 | ✅ | pytest 692 passed；五道防线全 PASS；契约断链=0 漂移=0；tsc 0 新错误；build 成功 |

## 五道防线状态

| 批次 | 契约守卫 | SQL | 慢查询 | 变异 | 施压 |
|------|---------|-----|--------|------|------|
| 第十九轮 | ✅ | ✅ | ✅ | ✅ | ✅ |

> 变异探针 caught=5 escaped=0 drift=1（锚点漂移为连接池上限 200→201，非本轮改动），还原后全量=OK。

## 当前 git 状态

- 测试：**692 passed / 0 failed**（29 排除）
- 前端：tsc 0 新错误 + build 成功（dashboard provider 卡片改）
- 契约：断链=0 漂移=0（provider_stats 新字段为增量，快照已 --update）
- 版本：**v2.16.0**

## 边界声明（诚实）

- **权重调度仅在 `model="auto"` 时生效**：`model="gpt-4"` 等具体模型仍走原有模型→provider 路由，不受权重影响
- **配额耗尽 fallback 有上限**：`max_provider_attempts = len(provider_weights)`，超过后抛 `RuntimeError("no available provider")`
- **Provider 熔断器独立于账号级熔断器**：provider 熔断记录的是"该 provider 全部账号不可用"的连续失败次数，不是账号级别的熔断
- **图片生图权重调度**：`get_available_access_token` 在 provider 配额耗尽/熔断时直接抛 RuntimeError（不 fallback 到其他 provider，因图片调度 QoS 更高，选错 provider 出图失败影响更大）

---

## 前轮历史

见 workflow_status.md 第十八轮（v2.10.0 失败分类中枢收尾）及更早轮次。