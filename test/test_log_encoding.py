"""3.3.4：Windows 中文日志经 GBK 管道偶发 UnicodeEncodeError 的容错回归测试。

场景：Windows 下 stderr/管道编码严格（GBK 对生僻字/emoji 抛 UnicodeEncodeError），
日志含中文时并发写入偶发崩溃。_SafeStreamHandler 应在编码异常时用 errors='replace'
替换重写，保证不崩溃、不丢失日志行语义。
"""

from __future__ import annotations

import logging

from utils.log import _SafeStreamHandler


class _StrictPipeStream:
    """模拟编码严格管道（如 Windows GBK 对生僻字符 / emoji 抛错）。

    write 按 self.encoding 严格编码，含不可编码字符时抛 UnicodeEncodeError；
    替换后的 ASCII 串可成功写入。
    """

    encoding = "ascii"

    def __init__(self) -> None:
        self.writes: list[str] = []

    def write(self, message: str) -> None:
        try:
            message.encode(self.encoding, errors="strict")
        except UnicodeEncodeError:
            raise
        self.writes.append(message)

    def flush(self) -> None:
        pass


def _make_record(message: str) -> logging.LogRecord:
    return logging.LogRecord("test_log_encoding", logging.ERROR, __file__, 1, message, None, None)


def test_encoding_error_does_not_crash_and_falls_back() -> None:
    stream = _StrictPipeStream()
    handler = _SafeStreamHandler(stream)
    handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))

    # 中文 + emoji：严格管道必然抛 UnicodeEncodeError
    record = _make_record("登录失败：😀 token 已过期")

    # 不应抛出，且 fallback 输出必须存在
    handler.emit(record)
    assert stream.writes, "编码异常后应写入替换输出"
    assert any("token" in line for line in stream.writes), "fallback 应保留日志语义内容"


def test_ascii_log_writes_normally() -> None:
    stream = _StrictPipeStream()
    handler = _SafeStreamHandler(stream)
    handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))

    handler.emit(_make_record("account refreshed"))
    assert any("account refreshed" in line for line in stream.writes)


def test_formatter_error_delegates_to_handle_error() -> None:
    """异常路径不能二次崩溃：handleError 需吞掉（logging 约定），不抛到调用方。"""
    stream = _StrictPipeStream()

    class _BrokenHandler(_SafeStreamHandler):
        def format(self, record: logging.LogRecord) -> str:  # noqa: A002
            raise RuntimeError("formatter boom")

    handler = _BrokenHandler(stream)
    # 不抛异常（logging.handleError 内部吞掉并打印 traceback）
    handler.emit(_make_record("anything"))
