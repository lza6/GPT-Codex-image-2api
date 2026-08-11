# 容量规划与成本优化设计文档

> 日期：2026-08-11
> 对应需求：v3.2 批次 5.1.1 容量仪表盘 + 5.1.2 成本优化

## 5.1.1 容量预测仪表盘

**现状**：后端 `_collect_capacity` + `/api/dashboard/capacity` 端点已存在，测试已覆盖。前端 dashboard 页面从未调用此端点。

**方案**：前端补齐消费，不触后端。

- `api.ts` 加 `fetchCapacity()` / `CapacityStats` 类型
- `dashboard/page.tsx` 加容量卡片区域（日均请求/活跃账号/单号日均/扩缩容建议），复用已有 recharts 趋势图

## 5.1.2 成本优化

**架构**：新建 `services/cost_service.py`（轻量模块，类似 `metrics_service.py` 单例模式）

**数据源组合**：
1. 每账号 Token 消耗 → 读 `usage_agg` 聚合缓存的 `by_summary` 分布
2. 每 Provider 成本 → `provider_scheduler.get_provider_stats` 的账号分布
3. 代理成本 → `kookeey_service.get_traffic_overview` 流量 + 余额
4. 成本概览 → 以上三组合并

**后端**：
- `services/cost_service.py`：`CostService` 类，`get_cost_overview()` 返回聚合数据
- `api/dashboard.py`：加 `/api/dashboard/cost` 端点
- `test/test_cost_service.py`：单测覆盖

**前端**：
- `api.ts` 加 `fetchCostOverview()` / `CostOverview` 类型
- `dashboard/page.tsx` 加成本卡片（流量余额/配额消耗/成本趋势）

**边界**：
- 无 kookeey 配置时降级（只显示 "未配置" 不报错）
- 无日志数据时显示占位 0
- 所有数据只读聚合缓存，不触全量扫描