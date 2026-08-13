"""fomimage 自动注册子模块（v2.36.0）。

- temp_mail：temp-mail.org 一次性邮箱收件
- engine：注册流水线（建邮箱 → signup → 收码 → verify → signin → 查积分）
- coordinator：批量注册 + 自动补号 + 号池健康
"""
from services.registration.fomimage.coordinator import fomimage_registration_coordinator

__all__ = ["fomimage_registration_coordinator"]
