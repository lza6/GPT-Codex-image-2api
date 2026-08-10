"""Apply remaining patches."""
with open('services/account_service.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix list_accounts record_accounts_count injection
old = '''                result.append(account)
            return result'''

new = '''                result.append(account)
                # 注入 Prometheus 账号数量指标
                try:
                    from services.prometheus_metrics import record_accounts_count
                    record_accounts_count(account.get("provider", "chatgpt"), account.get("status", "正常"))
                except Exception:
                    pass
            return result'''

content = content.replace(old, new)

with open('services/account_service.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('account_service.py patched v2')
