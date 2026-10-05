import asyncio
import sys

import pytest

pytest.importorskip("mcp")
pytestmark = pytest.mark.skipif(sys.version_info < (3, 10), reason="MCP SDK needs Python 3.10+")

from wxfetch import VerificationRequired, mcp_server  # noqa: E402


def _tools():
    server = mcp_server.build_server()
    return server, {t.name for t in asyncio.run(server.list_tools())}


def test_tools_registered():
    _, names = _tools()
    assert {"fetch_wechat_article", "parse_wechat_html"} <= names


def _call(server, name, args):
    res = asyncio.run(server.call_tool(name, args))
    # v2 returns a CallToolResult-like object; v1 returns (content, structured)
    structured = getattr(res, "structured_content", None) or getattr(res, "structuredContent", None)
    if structured is None and isinstance(res, tuple):
        structured = res[1]
    return structured.get("result", structured) if isinstance(structured, dict) and "ok" not in structured else structured


def test_parse_tool(fixture_html):
    server, _ = _tools()
    d = _call(server, "parse_wechat_html", {"html": fixture_html("text_post_trimmed.html"),
                                             "url": "https://mp.weixin.qq.com/s/ExampleTextPost01", "max_chars": 20})
    assert d["ok"] is True and d["truncated"] is True
    assert d["account_nickname"] == "示例公众号" and len(d["content_markdown"]) == 20


def test_fetch_tool_reports_verification(monkeypatch):
    def boom(url):
        raise VerificationRequired("verification page for every UA")

    monkeypatch.setattr(mcp_server, "_fetch", boom)
    server, _ = _tools()
    d = _call(server, "fetch_wechat_article", {"url": "https://mp.weixin.qq.com/s/ExampleTextPost01"})
    assert d["ok"] is False and d["error"] == "verification_required" and "parse_wechat_html" in d["hint"]
