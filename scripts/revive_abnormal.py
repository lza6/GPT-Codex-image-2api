#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性救号脚本：对异常账号跑 passwordless OTP 登录，成功则换新 token + 回写凭证。

链路：authorize → (停密码页则 passwordless/send-otp 触发发码) → 98faka 取码
      → email-otp/validate → exchange → 换 access_token key + 存 mail_credential/GPT密码。

前置：服务需停止（避免与本脚本并发写 accounts.json）。
用法：
  uv run python scripts/revive_abnormal.py --limit 3        # 先试 3 个
  uv run python scripts/revive_abnormal.py --email x@y.com  # 单个调试
  uv run python scripts/revive_abnormal.py                  # 全部（自动跳过已正常）
"""
from __future__ import annotations

import argparse
import json
import sys
import time

sys.path.insert(0, ".")

from services.account_service import account_service  # noqa: E402
from services.otp_login_service import otp_login_service  # noqa: E402
from services.proxy_service import kookeey_proxy_for  # noqa: E402

RECOVER_FILE = "data/_recover_payload.json"
V2RAY = "http://127.0.0.1:10808"  # 出墙代理（kookeey 需经此中转到住宅 IP）


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="最多处理多少个")
    ap.add_argument("--email", default="", help="只处理指定邮箱")
    ap.add_argument("--sleep", type=int, default=18, help="账号间隔秒数（防 OpenAI 同 IP send-otp 限流）")
    ap.add_argument("--offset", type=int, default=0, help="从第几个(1起)开始处理")
    ap.add_argument("--proxy", choices=["kookeey", "v2ray"], default="kookeey",
                    help="出口代理：kookeey=每号独立住宅IP(需v2ray开TUN)，v2ray=共享翻墙IP")
    args = ap.parse_args()

    recs = json.load(open(RECOVER_FILE, encoding="utf-8"))
    print(f"待救账号 {len(recs)} 个（回灌数据）", flush=True)

    ok = fail = skip = 0
    for i, rec in enumerate(recs, 1):
        if i < args.offset:
            continue
        email = rec["email"]
        if args.email and email.lower() != args.email.lower():
            continue
        if args.limit and (ok + fail) >= args.limit:
            break

        old_token = rec["access_token"]
        acct = account_service.get_account(old_token)
        if not acct:
            print(f"[{i}] {email} 不在库，跳过", flush=True)
            skip += 1
            continue
        if str(acct.get("status") or "") == "正常":
            print(f"[{i}] {email} 已正常，跳过", flush=True)
            skip += 1
            continue

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

        if not args.email and i < len(recs):
            time.sleep(args.sleep)

    print(f"\n完成：成功 {ok}，失败 {fail}，跳过 {skip}", flush=True)


if __name__ == "__main__":
    main()
