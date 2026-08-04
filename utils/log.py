import base64
import binascii
import json
import logging
import re
from typing import Any


class _SafeStreamHandler(logging.StreamHandler):
    """3.3.4：Windows 中文日志经 GBK 管道偶发 UnicodeEncodeError 的容错 handler。

    底层 stream.write 编码失败（生僻字/emoji 不在管道编码集内）时，
    用 errors='replace' 替换重写，保证日志进程不崩溃、行语义不丢失。

    注意：必须整体覆盖 emit——父类 StreamHandler.emit 会把所有异常吞进
    handleError，直接调 super().emit 永远捕获不到 UnicodeEncodeError。
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
            self.stream.write(message + self.terminator)
            self.flush()
        except UnicodeEncodeError:
            try:
                message = self.format(record)
                encoding = getattr(self.stream, "encoding", None) or "utf-8"
                fallback = message.encode(encoding, errors="replace").decode(encoding, errors="replace")
                self.stream.write(fallback + self.terminator)
                self.flush()
            except Exception:
                self.handleError(record)
        except Exception:
            self.handleError(record)


class Logger:
    _DATA_URL_RE = re.compile(r"data:image/[^;]+;base64,[A-Za-z0-9+/=]+")
    _JSON_B64_RE = re.compile(r'("b64_json"\s*:\s*")([A-Za-z0-9+/=]+)(")')

    def __init__(self, name: str = "chatgpt2api") -> None:
        self._logger = logging.getLogger(name)
        if not self._logger.handlers:
            handler = _SafeStreamHandler()
            handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
            self._logger.addHandler(handler)
        self._logger.setLevel(logging.DEBUG)
        self._logger.propagate = False

    def _enabled(self, level: str) -> bool:
        try:
            from services.config import config
            levels = set(config.log_levels)
        except Exception:
            levels = set()
        return level in (levels or {"info", "warning", "error"})

    def _mask_string(self, value: str, keep: int = 10) -> str:
        if len(value) <= keep:
            return value
        return value[:keep] + "..."

    def _mask_base64(self, value: str) -> str:
        if value.startswith("data:") and ";base64," in value:
            header, _, data = value.partition(",")
            return f"{header},{self._mask_string(data, 24)} (base64 len={len(data)})"
        return f"{self._mask_string(value, 24)} (base64 len={len(value)})"

    def _is_base64_string(self, value: str) -> bool:
        if len(value) < 64 or len(value) % 4 != 0:
            return False
        if not any(char in value for char in "+/="):
            return False
        try:
            base64.b64decode(value, validate=True)
            return True
        except (binascii.Error, ValueError):
            return False

    def _sanitize_string(self, value: str) -> str:
        stripped = value.strip()
        if stripped.startswith("data:") and ";base64," in stripped:
            return self._mask_base64(stripped)
        if self._is_base64_string(stripped):
            return self._mask_base64(stripped)
        sanitized = self._DATA_URL_RE.sub(lambda match: self._mask_base64(match.group(0)), value)
        sanitized = self._JSON_B64_RE.sub(
            lambda match: f'{match.group(1)}{self._mask_base64(match.group(2))}{match.group(3)}',
            sanitized,
        )
        if sanitized != value:
            return sanitized
        return value

    def _sanitize(self, value: Any) -> Any:
        if isinstance(value, dict):
            sanitized = {}
            for key, item in value.items():
                lowered_key = key.lower()
                if isinstance(item, str) and ("token" in lowered_key or lowered_key == "dx"):
                    sanitized[key] = self._mask_string(item)
                elif isinstance(item, str) and ("base64" in lowered_key or lowered_key == "b64_json"):
                    sanitized[key] = self._mask_base64(item)
                else:
                    sanitized[key] = self._sanitize(item)
            return sanitized
        if isinstance(value, list):
            return [self._sanitize(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self._sanitize(item) for item in value)
        if isinstance(value, str):
            return self._sanitize_string(value)
        return value

    def _message(self, value: Any) -> str:
        sanitized = self._sanitize(value)
        if isinstance(sanitized, str):
            return sanitized
        return json.dumps(sanitized, ensure_ascii=False, default=str)

    def debug(self, message: Any) -> None:
        if self._enabled("debug"):
            self._logger.debug(self._message(message))

    def info(self, message: Any) -> None:
        if self._enabled("info"):
            self._logger.info(self._message(message))

    def warning(self, message: Any) -> None:
        if self._enabled("warning"):
            self._logger.warning(self._message(message))

    def error(self, message: Any) -> None:
        if self._enabled("error"):
            self._logger.error(self._message(message))


logger = Logger()
