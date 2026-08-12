#!/usr/bin/env python3
"""救号脚本：对异常账号跑 passwordless OTP 登录，成功则换新 token + 回写凭证。

链路：authorize → (停密码页则 passwordless/send-otp 触发发码) → 98faka 取码
      → email-otp/validate → exchange → 换 access_token key + 存 mail_credential/GPT密码。

前置：服务需停止（避免与本脚本并发写 accounts.json）。
用法：
  uv run python scripts/revive_abnormal.py --dry-run                 # 只分类（可救/不可救），不联网
  uv run python scripts/revive_abnormal.py --limit 3                 # 先试 3 个
  uv run python scripts/revive_abnormal.py --email x@y.com           # 单个调试
  uv run python scripts/revive_abnormal.py                           # 全部（自动跳过已正常）

4.2 增强：
- --dry-run：输出「可救 / 不可救」分类清单（不可救=库内无账号/无取件凭证/已正常），
  不真正救号、不联网。dry-run 与实跑都会对「库内账号无取件凭证」落
  revive_skipped=true + revive_skip_reason（避免 watcher 每轮空转）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, ".")

from services.account_service import account_service  # noqa: E402
from services.otp_login_service import otp_login_service  # noqa: E402
from services.proxy_service import kookeey_proxy_for  # noqa: E402

RECOVER_FILE = "data/_recover_payload.json"
V2RAY = "http://127.0.0.1:10808"  # 出墙代理（kookeey 需经此中转到住宅 IP）


def _has_mail_credential(rec: dict) -> bool:
    """回灌数据是否含取件凭证（client_id + ms_rt + outlook_pw，98faka 取码用）。"""
    return bool(rec.get("client_id") and rec.get("ms_rt") and rec.get("outlook_pw"))


def classify_rec(acct_svc, rec: dict) -> tuple[str, str]:
    """对单条回灌记录分类（不联网）。

    返回 (category, reason)：
      - revivable:    可救（库内异常账号 + 有取件凭证）
      - not_in_lib:   库内无账号（无法落 revive_skipped 标记）
      - already_ok:   账号已正常（无需救，不标记）
      - no_credential: 无取件凭证（落 revive_skipped 标记）
    """
    email = str(rec.get("email") or "").strip()
    old_token = str(rec.get("access_token") or "").strip()
    if not email or not old_token:
        return "not_in_lib", "无邮箱或token"
    acct = acct_svc.get_account(old_token)
    if not acct:
        return "not_in_lib", "库内无账号"
    if str(acct.get("status") or "") == "正常":
        return "already_ok", "账号已正常"
    if not _has_mail_credential(rec):
        return "no_credential", "无取件凭证"
    return "revivable", ""


def _mark_revive_skipped(acct_svc, rec: dict, reason: str) -> None:
    """对库内账号落 revive_skipped 标记（避免 watcher 每轮空转）。失败不阻断。"""
    token = str(rec.get("access_token") or "").strip()
    if not token:
        return
    try:
        acct_svc.update_account(token, {"revive_skipped": True, "revive_skip_reason": reason}, quiet=True)
    except Exception:  # noqa: BLE001
        pass


def classify_recs(acct_svc, recs: list[dict], *, offset: int = 0, email: str = "", limit: int = 0) -> dict:
    """分类全部回灌记录（不联网）。

    返回：
      {"revivable": [(index, rec)], "skipped": [(index, rec, reason)]}
    并对「库内账号无取件凭证」的 rec 落 revive_skipped 标记（dry-run 也落，见文件头注释）。
    limit 只限制可救数量（与实跑一致：跳过不计入 limit）。
    """
    result: dict = {"revivable": [], "skipped": []}
    for i, rec in enumerate(recs, 1):
        if i < offset:
            continue
        rec_email = str(rec.get("email") or "").strip()
        if email and rec_email.lower() != email.lower():
            continue
        category, reason = classify_rec(acct_svc, rec)
        if category == "revivable":
            result["revivable"].append((i, rec))
        else:
            result["skipped"].append((i, rec, reason))
            if category == "no_credential":
                _mark_revive_skipped(acct_svc, rec, reason)
    if limit:
        result["revivable"] = result["revivable"][:limit]
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="最多处理多少个")
    ap.add_argument("--email", default="", help="只处理指定邮箱")
    ap.add_argument("--sleep", type=int, default=18, help="账号间隔秒数（防 OpenAI 同 IP send-otp 限流）")
    ap.add_argument("--offset", type=int, default=0, help="从第几个(1起)开始处理")
    ap.add_argument("--dry-run", action="store_true",
                    help="只输出可救/不可救分类清单，不救号不联网（仅落 revive_skipped 标记）")
    ap.add_argument("--proxy", choices=["kookeey", "v2ray"], default="kookeey",
                    help="出口代理：kookeey=每号独立住宅IP(需v2ray开TUN)，v2ray=共享翻墙IP")
    args = ap.parse_args()

    if not os.path.exists(RECOVER_FILE):
        print(f"[错误] 缺少救号数据文件 {RECOVER_FILE}", flush=True)
        print("  该文件是遗留异常号的取件凭证回灌数据（每行需含 email/access_token/client_id/ms_rt/outlook_pw/gpt_pw）。", flush=True)
        print("  需先从凭据 txt 解析生成；解析口径参考 scripts/test_outlook_token_mailbox.py。", flush=True)
        sys.exit(2)
    with open(RECOVER_FILE, encoding="utf-8") as fh:
        recs = json.load(fh)
    print(f"待救账号 {len(recs)} 个（回灌数据）", flush=True)

    classified = classify_recs(
        account_service, recs,
        offset=args.offset, email=args.email, limit=args.limit,
    )

    # ---- dry-run：只输出分类，不救号不联网 ----
    if args.dry_run:
        print(f"\n== 可救账号（{len(classified['revivable'])}） ==", flush=True)
        for i, rec in classified["revivable"]:
            print(f"  [{i}] {rec['email']}", flush=True)
        print(f"\n== 不可救账号（{len(classified['skipped'])}） ==", flush=True)
        for i, rec, reason in classified["skipped"]:
            print(f"  [{i}] {rec['email']}  {reason}", flush=True)
        print("\ndry-run 完成：可救/不可救分类如上；无取件凭证账号已落 revive_skipped 标记（避免 watcher 空转）。", flush=True)
        return

    # ---- 实跑：只对可救账号救号 ----
    ok = fail = 0
    total = len(classified["revivable"])
    for pos, (i, rec) in enumerate(classified["revivable"], 1):
        email = rec["email"]
        old_token = rec["access_token"]

        # 取件凭证：client_id + 微软 refresh_token + outlook 邮箱密码（98faka 取码用）
        mail_cred = {
            "client_id": rec["client_id"],
            "refresh_token": rec["ms_rt"],
            "email": email,
            "password": rec["outlook_pw"],
        }
        # 代理：kookeey=每号住宅IP(需TUN)，v2ray=共享IP；kookeey未配置则回退v2ray
        proxy_url = kookeey_proxy_for(email) if args.proxy == "kookeey" else V2RAY
        if not proxy_url:
            proxy_url = V2RAY
        print(f"[{i}/{len(recs)}] 救 {email} (用 {args.proxy}) ...", flush=True)
        try:
            result = otp_login_service.login(
                email,
                rec["gpt_pw"],
                mail_credential=mail_cred,
                proxy_url=proxy_url,
                use_cf_solver=False,
            )
        except Exception as exc:  # noqa: BLE001
            result = {"ok": False, "error": f"exception:{type(exc).__name__}"}

        if result.get("ok") and result.get("access_token"):
            token_data = {
                "access_token": result["access_token"],
                "refresh_token": str(result.get("refresh_token") or ""),
                "id_token": str(result.get("id_token") or ""),
            }
            new_token = account_service._apply_refreshed_tokens(old_token, token_data, "manual_revive")
            account_service.update_account(
                new_token,
                {
                    "password": rec["gpt_pw"],
                    "mail_credential": {"client_id": rec["client_id"], "refresh_token": rec["ms_rt"]},
                    "source_type": "otp",
                    "status": "正常",
                    "login_error": "",
                    "last_refresh_error": "",
                    "last_token_refresh_error": "",
                },
                quiet=True,
            )
            ok += 1
            print(f"   [OK] {email} 已救活", flush=True)
        else:
            fail += 1
            print(f"   [FAIL] {email}: {result.get('error')}", flush=True)

        if not args.email and pos < total:
            time.sleep(args.sleep)

    print(f"\n完成：成功 {ok}，失败 {fail}，跳过 {len(classified['skipped'])}", flush=True)


if __name__ == "__main__":
    main()
