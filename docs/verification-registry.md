# 验证登记表（Verification Registry）

> **用途**：记录"当前已验证的真实基线"，让下次会话**先读本表**再决定要不要重跑——避免每次都盲目重复跑慢查询/防线/全量测试。
> **使用协议**（写进 SKILL.md 会话启动协议）：
> 1. 动手前先读本表 + `workflow_status.md` 最新一轮。
> 2. 只在**改动落到某区域**时才重跑该区域对应的验证；没碰的区域沿用本表结论，不重跑。
> 3. 每次改动后**更新本表**：标注改了哪个区域、对应验证的新结果与日期。
> 4. 「已知 flaky / 边界」列里的事项**不要重复追查**（已定性，非回归）。

---

## 一、当前验证基线（最新一轮：v2.9.0 号池救活 + 版本对齐 + 智能重建）

| 项 | 结果 | 范围/说明 | 日期 | 证据 |
|----|------|-----------|------|------|
| 全量单测 | **457 passed / 0 failed**（33 live/redis 排除） | 全 test/ | 2026-08-07 | `pytest -q` |
| 五道防线·契约守卫 | PASS（断链=0 漂移=0） | provider/mail_credential 新字段无契约破坏 | 2026-08-07 | reports/contract/ |
| 五道防线·SQL 审查 | PASS（P0=0 P1=0） | 曾误报 `_extract_code_from_text(f"..")` 撞 `text(f"` 启发式→改名 `_extract_otp_code` 消除 | 2026-08-07 | reports/sqlaudit/ |
| 五道防线·慢查询 | PASS（热点 2 处，P3 既有） | 账号/DB 两处长尾，非本轮引入 | 2026-08-07 | reports/slowquery/ |
| 五道防线·极限施压 | PASS（8/8） | 并发突刺/慢存储/存储并发写一致性 | 2026-08-07 | reports/stress/ |
| 五道防线·变异探针 | caught=6 escaped=0（**还原后全量=flaky**，见边界） | 6 个种子变异全被抓 | 2026-08-07 | reports/mutation/ |
| 前端 | tsc 0 错误 + build 成功 | 本轮未改前端逻辑 | 2026-08-07 | `npm run build` |
| lint | ruff 0 错误（改动文件） | otp_login_service + 2 新测试文件 | 2026-08-07 | `ruff check` |

## 二、本轮新增/改动区域 → 对应验证

| 区域 | 改动 | 验证 | 状态 |
|------|------|------|------|
| 取件 Graph 迁移 | `otp_login_service._fetch_otp_code` 改 Graph 优先/98faka 兜底 + `_graph_access_token/_graph_list_mails/_poll_graph_otp/_graph_code_from_full_body` | `test_otp_graph_fetch.py` 12 项（调度/全文兜底/token失败回退/无码不双轮询/无凭证直走98faka） | ✅ |
| passwordless 发码 | `_trigger_passwordless_otp` | 同上（200/非200/异常） | ✅ |
| 取件时间 UTC | `_mail_time` 统一 aware | 同上（naive/Z/偏移/非法/date键） | ✅ |
| OTP 降级 | `account_service` watcher重登+导入两处 | `test_otp_login.py` + `test_account_password_import.py` | ✅（既有） |
| 每号住宅 IP | `proxy_service.kookeey_proxy_for` + `config.get_kookeey_settings` | `test_kookeey_providers.py`（粘性/禁用/缺字段/自定义端口国家） | ✅ |
| 多提供商地基 | `services/providers/` + normalize 接线 | `test_kookeey_providers.py::TestProvidersRegistry` 8 项 | ✅ |
| 批量救号脚本 | `scripts/revive_abnormal.py` | 结构/字段校验已核（data 74 条字段齐）；**真实批量跑=用户决定（烧配额+需代理）** | ⚠️ 边界 |
| 智能重建 | `启动chatgpt2api.bat` + `scripts/web_stamp.ps1` | 指纹脚本稳定性实测（VERSION/CHANGELOG 改动→哈希变）；bat GBK 逐行验证中文完好 | ✅（未整跑 bat，避免中断在跑服务） |

## 三、已知 flaky / 边界（**不要重复追查**）

- **变异探针「还原后全量」偶发 FAIL**：Windows GBK 控制台，并发中文日志偶发 `UnicodeEncodeError` 致全量重跑偶发失败。已定性为**环境 flaky 非业务回归**（对照实验 stash/恢复均 308 passed；本轮独立全量 457 passed）。生产 Docker/Linux 无此问题。
- **真实上游图片/OTP/Graph 联网**：live 测试默认排除，需真实凭证+烧配额，由用户手动 `-m live` 自测。
- **71 个遗留异常号**：在「mail_credential 入库」功能**之前**导入，池内无取件凭证 → watcher 自动救活对它们无效，**只能 `revive_abnormal.py` + 外部 payload 一次性救**；新导入号才带凭证可被自动救。
- **代理出口（kookeey/v2ray TUN 分流）**：方案§四未定稿，属用户网络/基础设施决策，代码层 `kookeey_proxy_for` 已就绪待配置。

## 四、各区域"最近改动"速记（下次只重测这些）

- 2026-08-07：`services/otp_login_service.py`、`account_service.py`、`proxy_service.py`、`config.py`、`services/providers/`、`scripts/revive_abnormal.py`、`scripts/web_stamp.ps1`、`启动chatgpt2api.bat`、`VERSION`、`CHANGELOG.md` → 重跑：otp/proxy/providers 相关测试 + 五道防线。
- 前端本轮无逻辑改动（仅文档/版本）→ 前端只需 build，无需重跑 e2e。

---

*本表随每轮改动更新；历史轮次的详细矩阵见 `workflow_status.md`。*
