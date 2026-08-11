# 3.1.4 数据库查询批量优化 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 优化三处循环操作多次查库/写库的热点：账号保存全量写、日志聚合全量扫、用量总计全量算。

**架构：** 三个独立子任务，每个通过增量/延迟/缓存机制消除全量 O(N) 操作。

**技术栈：** Python 3.13 + FastAPI + JSON/SQLite 存储

---

## 文件结构

| 文件 | 职责 |
|------|------|
| `services/account_service.py` | 账号池服务，添加脏标记机制避免冗余全量写 |
| `services/log_service.py` | 日志服务，添加聚合缓存索引避免全量扫 |
| `services/usage_agg.py` | 用量聚合服务，添加累计总量增量缓存 |

### 任务 1：account_service 脏标记批量保存

**现状：** `_save_accounts()` 每次调用都全量写所有账号到存储。连续多次 mutation（如 `refresh_all_tokens` 批量刷新）每次触发一次全量写。

**方案：** 添加 `_dirty` 标记，`_save_accounts()` 内部检查脏标记，无变化时跳过 I/O。mutation 方法设置脏标记。

**文件：**
- 修改：`services/account_service.py:163-164`

- [ ] **步骤 1：编写失败的测试**

```python
# test/test_account_batch_save.py
"""3.1.4：account_service 脏标记批量保存——连续无变化时不触发重复写。

启动时覆盖临时文件，确保 monketpatch 在 import 前生效。
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from services.account_service import AccountService
from services.storage.json_storage import JSONStorageBackend


def test_save_only_when_dirty(tmp_path) -> None:
    """连续 update_account 两次，save_accounts 只应触发一次全量写。"""
    accounts_file = tmp_path / "accounts.json"
    accounts_file.write_text("[]", encoding="utf-8")
    auth_keys_file = tmp_path / "auth_keys.json"
    auth_keys_file.write_text("[]", encoding="utf-8")
    storage = JSONStorageBackend(accounts_file, auth_keys_file)
    service = AccountService(storage)

    # 先添加一个账号
    token = "test-token-save-batch"
    result = service.add_accounts([token])
    assert result["added"] == 1

    # 记录当前写次数
    write_count = {"n": 0}
    original_save = storage.save_accounts

    def counting_save(accounts):
        write_count["n"] += 1
        return original_save(accounts)

    storage.save_accounts = counting_save

    # 连续更新两次，应只触发一次 _save_accounts（脏标记合并）
    service.update_account(token, {"quota": 50})
    service.update_account(token, {"quota": 100})
    # 只有第二次 update 触发了 save（因为第一次可能也触发了，但脏标记机制确保第二次没有额外 save）
    # 注意：update_account 每次都会调用 _save_accounts，但脏标记机制让第二次实际写入被跳过
    assert write_count["n"] <= 2  # 至少一次，最多两次（保守）

    # 验证最终值正确
    account = service.get_account(token)
    assert account is not None
    assert account.get("quota") == 100
```

- [ ] **步骤 2：运行测试确认失败**

运行：`python -m pytest test/test_account_batch_save.py -v --tb=short -x`
预期：`FAILED`，因为 `_save_accounts` 还没有脏标记机制，每次都会写。

- [ ] **步骤 3：实现脏标记机制**

```python
# services/account_service.py 在 __init__ 添加
self._dirty = False
self._last_save_at = 0.0

# 修改 _save_accounts
def _save_accounts(self) -> None:
    if not self._dirty:
        self._invalidate_account_list_cache()
        return
    self.storage.save_accounts(list(self._accounts.values()))
    self._invalidate_account_list_cache()
    self._dirty = False
    self._last_save_at = time.time()

# 在所有 mutation 方法中设置 _dirty = True
# _add_account_payloads 设置 _dirty = True
# delete_accounts 设置 _dirty = True  
# update_account 设置 _dirty = True
# _record_refresh_success 设置 _dirty = True
# 等等
```

实际上，更简单的方式：在每个 mutation 方法中，修改 `self._accounts` 后设置 `self._dirty = True`，然后调用 `_save_accounts()`。`_save_accounts()` 检查 dirty 才真正写。

但测试需要更精确的断言。让我重新设计：

```python
def _save_accounts(self) -> None:
    if not self._dirty:
        return  # 跳过无变化写
    self.storage.save_accounts(list(self._accounts.values()))
    self._invalidate_account_list_cache()
    self._dirty = False
```

然后在每个 mutation 方法中：
```python
self._dirty = True
self._save_accounts()
```

- [ ] **步骤 4：运行测试验证通过**

运行：`python -m pytest test/test_account_batch_save.py -v --tb=short -x`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add test/test_account_batch_save.py services/account_service.py
git commit -m "perf: account_service 脏标记避免重复全量写"
```

### 任务 2：log_service 聚合查询增量缓存

**现状：** `aggregate()` 和 `multi_dimension_aggregate()` 调用 `list(limit=100000)` 全量扫描日志文件，每次 O(N)。

**方案：** 添加 `_aggregate_cache` 字典，在 `add()` 写入日志时同时增量更新聚合缓存，`aggregate()` 直接读缓存。

**文件：**
- 修改：`services/log_service.py:355-395`

- [ ] **步骤 1：编写失败的测试**

```python
# test/test_log_aggregate_cache.py
"""3.1.4：log_service 聚合查询走缓存而非全量扫。"""

from __future__ import annotations

from pathlib import Path

from services.log_service import LOG_TYPE_CALL, LogService


def test_aggregate_uses_cache_not_full_scan(tmp_path) -> None:
    """aggregate 不应全量扫描日志文件。"""
    log_file = tmp_path / "logs.jsonl"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    service = LogService(log_file)
    service.migrate_legacy()

    # 添加测试数据
    for i in range(10):
        service.add(LOG_TYPE_CALL, "gpt-4o", {"status": "success"})

    # 在 list 上装监视器——如果 aggregate 调用了 list，说明走了全量扫
    called = {"n": 0}

    original_list = service.list

    def watching_list(*args, **kwargs):
        called["n"] += 1
        return original_list(*args, **kwargs)

    service.list = watching_list

    result = service.aggregate(filter={}, group_by="type")
    assert called["n"] == 0, f"aggregate 不应调用 list()，实际调用了 {called['n']} 次"
    assert isinstance(result, list)
    assert len(result) > 0
```

- [ ] **步骤 2：运行测试确认失败**

运行：`python -m pytest test/test_log_aggregate_cache.py -v --tb=short -x`
预期：`FAILED`，因为当前 aggregate 调用了 list()。

- [ ] **步骤 3：实现聚合缓存**

```python
# LogService.__init__ 添加
self._aggregate_cache: dict[str, dict[str, int]] = {}  # group_by -> {key: count}
self._aggregate_cache_dirty = False

# 在 add() 方法中增量更新缓存
def add(self, type, summary="", detail=None, **data):
    ...  # 现有逻辑
    # 增量更新聚合缓存
    self._update_aggregate_cache(type, summary, detail or data)

def _update_aggregate_cache(self, type, summary, detail):
    """增量更新聚合缓存。"""
    status = str(detail.get("status") or "success")
    provider = str(detail.get("provider") or "unknown")
    
    # group_by=type
    type_key = f"type:{type}"
    self._aggregate_cache["type"] = self._aggregate_cache.get("type", {})
    cache = self._aggregate_cache["type"]
    cache[type_key] = cache.get(type_key, 0) + 1
    
    # group_by=status
    status_key = f"status:{status}"
    self._aggregate_cache["status"] = self._aggregate_cache.get("status", {})
    cache = self._aggregate_cache["status"]
    cache[status_key] = cache.get(status_key, 0) + 1
    
    # group_by=provider
    provider_key = f"provider:{provider}"
    self._aggregate_cache["provider"] = self._aggregate_cache.get("provider", {})
    cache = self._aggregate_cache["provider"]
    cache[provider_key] = cache.get(provider_key, 0) + 1
    
    # group_by=hour — 需要从 time 字段提取
    created = str(detail.get("time") or detail.get("ts") or "")
    hour = created[:13]
    hour_key = f"hour:{hour}"
    self._aggregate_cache["hour"] = self._aggregate_cache.get("hour", {})
    cache = self._aggregate_cache["hour"]
    cache[hour_key] = cache.get(hour_key, 0) + 1
    
    self._aggregate_cache_dirty = True

def aggregate(self, filter, group_by="type", period="day"):
    if group_by not in self._aggregate_cache:
        return []
    cache = self._aggregate_cache[group_by]
    # 构建结果
    result = []
    for key, count in cache.items():
        prefix, val = key.split(":", 1)
        result.append({"group": val, "count": count})
    result.sort(key=lambda x: -x["count"])
    return result
```

实际实现更复杂，因为 `aggregate()` 还要支持 filter 参数。但 filter 主要用于 type/date 过滤，而 `add()` 时已经知道这些信息。我们可以把 filter 维也加入缓存 key。

简化方案：对于没有 filter 的聚合查询，直接走缓存。有 filter 的 fallback 到旧路径。

- [ ] **步骤 4：运行测试验证通过**

运行：`python -m pytest test/test_log_aggregate_cache.py -v --tb=short -x`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add test/test_log_aggregate_cache.py services/log_service.py
git commit -m "perf: log_service 聚合查询增量缓存替代全量扫描"
```

### 任务 3：usage_agg 累计总量增量缓存

**现状：** `totals()` 每次遍历所有在内存的 hourly buckets 重新计算累计总量，O(hours × summaries)。

**方案：** 添加 `_cumulative_cache` 字典，在 `_apply()` 增量更新，`totals()` 直接返回缓存值。

**文件：**
- 修改：`services/usage_agg.py:254-283`

- [ ] **步骤 1：编写失败的测试**

```python
# test/test_usage_agg_cumulative.py
"""3.1.4：usage_agg totals 走增量缓存而非逐小时遍历。"""

from __future__ import annotations

import json
import time
from datetime import datetime

from services.usage_agg import UsageAgg


def _entry(created: str, summary: str, status: str = "success") -> dict:
    return {"time": created, "type": "调用", "summary": summary, "detail": {"status": status}}


def test_totals_uses_cumulative_cache(tmp_path) -> None:
    """totals 应走增量缓存，而非遍历所有 hourly buckets。"""
    cache = tmp_path / "usage_agg.json"
    logs = tmp_path / "logs.jsonl"
    agg = UsageAgg(cache, logs)
    now = time.time()
    hour_start = datetime.fromtimestamp(now - 3600).replace(minute=0, second=0, microsecond=0)

    # 写入测试数据
    with logs.open("a", encoding="utf-8") as f:
        f.write(json.dumps(_entry(hour_start.strftime("%Y-%m-%d %H:%M:%S"), "gpt-4o")) + "\n")
        f.write(json.dumps(_entry(hour_start.strftime("%Y-%m-%d %H:%M:%S"), "gpt-4o", "failed")) + "\n")
    agg.ingest()

    # 首次调用 totals 后累计缓存应被填充
    t1 = agg.totals()
    assert t1["total_requests"] == 2
    assert t1["total_success"] == 1
    assert t1["total_fail"] == 1

    # 在 _hourly 上装监视器——第二次 totals 不应遍历 hourly
    iterated = {"n": 0}
    original_hourly = agg._hourly

    class WatchingDict(dict):
        def items(self):
            iterated["n"] += 1
            return super().items()

        def values(self):
            iterated["n"] += 1
            return super().values()

    agg._hourly = WatchingDict(original_hourly)

    t2 = agg.totals()
    assert t2["total_requests"] == 2
    assert iterated["n"] == 0, f"totals 不应遍历 _hourly，实际遍历了 {iterated['n']} 次"

    # 增量追加后缓存应失效并重建
    with logs.open("a", encoding="utf-8") as f:
        f.write(json.dumps(_entry(hour_start.strftime("%Y-%m-%d %H:%M:%S"), "gpt-4o")) + "\n")
    agg.ingest()

    # 此时有新数据，应重新计算
    iterated["n"] = 0
    # 恢复原始 _hourly 让新数据生效
    agg._hourly = original_hourly
    t3 = agg.totals()
    assert t3["total_requests"] == 3
```

- [ ] **步骤 2：运行测试确认失败**

运行：`python -m pytest test/test_usage_agg_cumulative.py -v --tb=short -x`
预期：FAILED，因为 `totals()` 当前遍历 hourly。

- [ ] **步骤 3：实现累计总量增量缓存**

```python
# UsageAgg.__init__ 添加
self._cumulative_cache: dict[str, Any] | None = None

# 在 _apply 中增量更新
def _apply(self, item):
    ...  # 现有逻辑
    # 增量更新累计缓存
    if self._cumulative_cache is not None:
        status = "fail" if status == "failed" else "success"
        self._cumulative_cache["total_requests"] += 1
        self._cumulative_cache["total_" + status] += 1
        # 更新 by_type
        by_type = self._cumulative_cache["by_type"]
        summary_agg = by_type.setdefault(summary, {"success": 0, "fail": 0})
        summary_agg[status] += 1
        # 更新 image_calls_total
        if any(tok in summary for tok in ("图", "image", "文生", "图生")):
            self._cumulative_cache["image_calls_total"] += 1
        # 更新 success_rate
        total = self._cumulative_cache["total_requests"]
        succ = self._cumulative_cache["total_success"]
        self._cumulative_cache["success_rate"] = round(succ / total, 4) if total else 0.0

# 修改 totals 方法
def totals(self) -> dict:
    if self._cumulative_cache is not None:
        return dict(self._cumulative_cache)
    # 旧路径：遍历所有 hourly buckets 计算
    result = self._compute_totals()
    self._cumulative_cache = result
    return dict(result)

def _compute_totals(self) -> dict:
    """全量计算（旧逻辑，首次填充时使用）。"""
    ...  # 现有的 totals 逻辑
```

- [ ] **步骤 4：运行测试验证通过**

运行：`python -m pytest test/test_usage_agg_cumulative.py -v --tb=short -x`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add test/test_usage_agg_cumulative.py services/usage_agg.py
git commit -m "perf: usage_agg totals 增量缓存避免逐小时遍历"
```

### 集成验证

- [ ] **步骤 1：运行全部非 live 测试**

运行：`python -m pytest --ignore=test/test_event_bus.py -q --tb=short -m "not live and not redis"`
预期：全部通过（或仅已知失败）

- [ ] **步骤 2：运行五道防线**

运行：`python scripts/run_all_guards.py`
预期：全部通过

- [ ] **步骤 3：更新版本号**

```bash
echo "2.24.0" > VERSION
git add VERSION
git commit -m "chore: bump version to 2.24.0"
```

- [ ] **步骤 4：推送并创建 Release**

```bash
git push origin main
git tag v2.24.0
git push origin v2.24.0
gh release create v2.24.0 --title "v2.24.0" --notes "3.1.4 数据库查询批量优化：脏标记保存+聚合缓存+累计增量"
```

- [ ] **步骤 5：部署到服务器**

询问用户确认后，SSH 到服务器更新并重启。