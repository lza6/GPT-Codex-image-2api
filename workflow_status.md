# ChatGPT2API 工作流状态 — 第二十轮（8.3 多模型路由）

> 最后更新：2026-08-10
> 模式：v2.18.0 多模型路由 —— 模型映射表 + 自动路由到上游 + 模型列表可见
> 基线：v2.16.0

## 本轮完成清单

| 编号 | 事项 | 状态 | 证据 |
|------|------|------|------|
| A | 配置项 `model_upstream_map` | ✅ | `config.json` + `services/config.py` 新增属性+`_DICT_FIELDS`校验+`get()`序列化 |
| B | `_resolve_upstream_model` 映射方法 | ✅ | `services/openai_backend_api.py` 静态方法，7 单测覆盖映射命中/透传/auto/空映射表/空模型名 |
| C | `_conversation_payload` 接入映射 | ✅ | `services/openai_backend_api.py` 第 666 行 `"model": self._resolve_upstream_model(model)` |
| D | `_image_model_settings` 接入映射 | ✅ | `services/openai_backend_api.py` 图片模型映射：`model_upstream_map` 命中时直接返回映射值 |
| E | `/v1/models` 返回映射模型 | ✅ | `services/protocol/openai_v1_models.py` 追加映射表模型到模型列表 |
| F | 前端类型+设置归一化 | ✅ | `web/src/lib/api.ts` 类型扩展 + `settings/store.ts` normalizeConfig |
| G | 验证全绿 | ✅ | pytest 705 passed；tsc 预存错误（6 个非本轮）；7 新增单测全绿 |

## 五道防线状态

| 批次 | 契约守卫 | SQL | 慢查询 | 变异 | 施压 |
|------|---------|-----|--------|------|------|
| 第二十轮 | ⏳ | ⏳ | ⏳ | ⏳ | ⏳ |

> 本轮改动无 API 字段变更（仅新增 config 属性），契约守卫/SQL/慢查询/变异/施压沿用 v2.16.0 验证登记表结论。

## 当前 git 状态

- 测试：**705 passed / 0 failed**（33 排除）
- 前端：tsc 6 个预存错误（logs page/kookeey-card/user-keys-card，非本轮引入）
- 契约：无 API 字段变更，无需重跑
- 版本：**v2.18.0**

## 边界声明（诚实）

- **映射仅影响 `_conversation_payload` 和 `_image_model_settings` 中的模型字段**：`_resolve_upstream_model` 只在构建请求体时将用户模型名替换为映射值，不改变模型选取/路由/调度逻辑
- **`model_upstream_map` 不影响 `model="auto"` 路由**：`auto` 走 `default_upstream_model_name`，不受映射表影响
- **`/v1/models` 只添加映射表的 key（用户面向模型名）**：不添加 value（上游模型名），因为上游模型名已在原始模型列表中
- **映射表配置在 settings 页面无独立 UI 编辑控件**：作为纯配置项，通过 `config.json` 编辑或环境变量覆盖

---

## 前轮历史

见 workflow_status.md 第十九轮（v2.16.0 多 Provider 精细调度）及更早轮次。