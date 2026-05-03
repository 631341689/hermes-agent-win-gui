"""StdioTransport must emit UTF-8 on the binary layer when stdout is a
narrow text wrapper (Windows GBK / misconfigured ASCII) so gateway.ready
JSON never dies on skin emoji."""

import io
import json
import threading

from tui_gateway.transport import StdioTransport


def test_stdio_transport_utf8_surrogates_narrow_text_codec():
    raw = io.BytesIO()
    text = io.TextIOWrapper(
        raw,
        encoding="ascii",
        errors="strict",
        line_buffering=True,
    )
    lock = threading.Lock()
    transport = StdioTransport(lambda: text, lock)
    payload = {"emoji": "⚕", "text": "hello"}
    assert transport.write(payload) is True
    text.flush()
    text.detach()
    raw.seek(0)
    line = raw.read().decode("utf-8").strip()
    assert json.loads(line) == payload
