"""结构化日志字段过滤测试（event/request_id/result）。

验证 log_service.list 支持字段级过滤：
- event= 精确匹配 detail.event
- request_id= 精确匹配 item.request_id 或 detail.request_id
- result= 精确匹配 detail.result
- 向后兼容：不传新参数时行为不变
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from services.log_service import LogService


class TestLogsFieldFilter(unittest.TestCase):
    def _make_service(self, tmp_dir: Path) -> LogService:
        return LogService(tmp_dir / "logs.jsonl")

    def _seed_logs(self, service: LogService) -> None:
        # 直接写结构化日志条目（绕过 log() 的 request_id 注入）
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".jsonl", encoding="utf-8") as f:
            entries = [
                {"ts": "2026-08-08T10:00:00.000", "level": "info", "logger": "chatgpt2api", "request_id": "req-001", "type": "image", "summary": "生成图片", "detail": {"event": "image_stream_error", "result": "fail", "account_email": "a@x.com"}},
                {"ts": "2026-08-08T10:01:00.000", "level": "info", "logger": "chatgpt2api", "request_id": "req-002", "type": "image", "summary": "生成图片", "detail": {"event": "image_stream_error", "result": "success", "account_email": "b@x.com"}},
                {"ts": "2026-08-08T10:02:00.000", "level": "info", "logger": "chatgpt2api", "request_id": "req-003", "type": "text", "summary": "文本请求", "detail": {"event": "text_complete", "result": "success", "account_email": "a@x.com"}},
                {"ts": "2026-08-08T10:03:00.000", "level": "info", "logger": "chatgpt2api", "request_id": "req-004", "type": "image", "summary": "生成图片", "detail": {"event": "image_poll_timeout", "result": "fail", "account_email": "c@x.com"}},
            ]
            for e in entries:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
            tmp_path = f.name
        # 把种子文件注册为 2026-08-08 的天文件
        day_file = service._daily_path("2026-08-08")
        day_file.parent.mkdir(parents=True, exist_ok=True)
        day_file.write_text(Path(tmp_path).read_text(encoding="utf-8"), encoding="utf-8")
        Path(tmp_path).unlink()

    def test_event_filter(self):
        """event= 精确命中 detail.event。"""
        with tempfile.TemporaryDirectory() as td:
            service = self._make_service(Path(td))
            self._seed_logs(service)
            items = service.list(event="image_stream_error", start_date="2026-08-08", end_date="2026-08-08")
            self.assertEqual(len(items), 2)
            self.assertTrue(all(str(i.get("detail", {}).get("event")) == "image_stream_error" for i in items))

    def test_request_id_filter(self):
        """request_id= 精确命中（跨天不串）。"""
        with tempfile.TemporaryDirectory() as td:
            service = self._make_service(Path(td))
            self._seed_logs(service)
            items = service.list(request_id="req-003", start_date="2026-08-08", end_date="2026-08-08")
            self.assertEqual(len(items), 1)
            self.assertEqual(str(items[0].get("request_id")), "req-003")

    def test_result_filter(self):
        """result= 精确命中 detail.result。"""
        with tempfile.TemporaryDirectory() as td:
            service = self._make_service(Path(td))
            self._seed_logs(service)
            items = service.list(result="fail", start_date="2026-08-08", end_date="2026-08-08")
            self.assertEqual(len(items), 2)

    def test_combined_filters(self):
        """组合过滤：type + event + result。"""
        with tempfile.TemporaryDirectory() as td:
            service = self._make_service(Path(td))
            self._seed_logs(service)
            items = service.list(type="image", event="image_stream_error", result="fail", start_date="2026-08-08", end_date="2026-08-08")
            self.assertEqual(len(items), 1)
            self.assertEqual(str(items[0].get("detail", {}).get("account_email")), "a@x.com")

    def test_backward_compatible(self):
        """不传新参数时行为不变（原有 type/account_email 过滤仍工作）。"""
        with tempfile.TemporaryDirectory() as td:
            service = self._make_service(Path(td))
            self._seed_logs(service)
            items = service.list(type="image", start_date="2026-08-08", end_date="2026-08-08")
            self.assertEqual(len(items), 3)
            items2 = service.list(account_email="a@x.com", start_date="2026-08-08", end_date="2026-08-08")
            self.assertEqual(len(items2), 2)

    def test_missing_fields_tolerated(self):
        """缺 detail/event/request_id 字段的日志不报错。"""
        with tempfile.TemporaryDirectory() as td:
            service = self._make_service(Path(td))
            day_file = service._daily_path("2026-08-08")
            day_file.parent.mkdir(parents=True, exist_ok=True)
            day_file.write_text(json.dumps({"ts": "2026-08-08T09:00:00.000", "type": "text", "summary": "旧格式"}) + "\n", encoding="utf-8")
            items = service.list(event="any", start_date="2026-08-08", end_date="2026-08-08")
            self.assertEqual(len(items), 0)
            items2 = service.list(start_date="2026-08-08", end_date="2026-08-08")
            self.assertEqual(len(items2), 1)


if __name__ == "__main__":
    unittest.main()
