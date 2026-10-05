"""Tiny MCP server (stdio) for agents: ``wxfetch-mcp``.

Tools
-----
- ``fetch_wechat_article(url)``  fetch a public mp.weixin.qq.com article
- ``parse_wechat_html(html)``    parse a saved article page (no network)

Requires Python 3.10+ (the MCP SDK is installed automatically there).
"""
from __future__ import annotations

import asyncio
import sys
from typing import Any, Optional

from .errors import ArticleUnavailable, InvalidURL, VerificationRequired, WxFetchError
from .extractor import extract_article
from .models import Article

INSTRUCTIONS = (
    "Read public WeChat Official Account (mp.weixin.qq.com) articles as Markdown. "
    "On failure the result has ok=false and error = verification_required | article_unavailable | "
    "invalid_url | fetch_error, with WeChat's reason. Never try to solve WeChat's verification captcha; "
    "tell the user and suggest opening the article in WeChat or saving the page as HTML for parse_wechat_html."
)


def _ok(art: Article, fmt: str, max_chars: int) -> dict[str, Any]:
    d = art.to_dict()
    truncated = False
    for k in ("content_markdown", "content_text"):
        if max_chars and len(d.get(k) or "") > max_chars:
            d[k] = d[k][:max_chars]
            truncated = True
    if fmt == "markdown":
        d.pop("content_text", None)
    elif fmt == "text":
        d.pop("content_markdown", None)
    d["images"] = d.get("images", [])[:30]
    d["ok"] = True
    d["truncated"] = truncated
    return d


def _err(exc: Exception, fetched: bool = True) -> dict[str, Any]:
    if isinstance(exc, VerificationRequired):
        hint = ("WeChat showed its 环境异常 verification page for every client tried. Try later or from another network, "
                "or open the article in WeChat/a browser, save the page as HTML and use parse_wechat_html."
                if fetched else
                "This HTML is WeChat's 环境异常 verification page, not the article. Save the page again after it shows the article.")
        return {"ok": False, "error": "verification_required", "message": str(exc), "hint": hint}
    if isinstance(exc, ArticleUnavailable):
        return {"ok": False, "error": "article_unavailable", "reason": exc.reason, "message": exc.message}
    if isinstance(exc, InvalidURL):
        return {"ok": False, "error": "invalid_url", "message": str(exc)}
    return {"ok": False, "error": "fetch_error", "message": f"{type(exc).__name__}: {exc}"}


def _fetch(url: str) -> Article:
    from . import fetch_article

    return fetch_article(url)


def _parse(html: str, url: str) -> Article:
    art = extract_article(html, url=url)
    art.fetched_with = "local-html"
    return art


def build_server():
    try:  # official MCP Python SDK v2
        from mcp.server.mcpserver import MCPServer as Server
    except ImportError:  # SDK v1.x
        from mcp.server.fastmcp import FastMCP as Server

    mcp = Server("wechat-article-fetcher", instructions=INSTRUCTIONS)

    @mcp.tool()
    async def fetch_wechat_article(url: str, format: str = "markdown", max_chars: int = 40000) -> dict[str, Any]:
        """Fetch a public WeChat Official Account article (mp.weixin.qq.com/s/...) and return
        title, account_nickname, author, publish_time (+08:00), content_markdown, images and
        extraction_method. format: markdown | text | both. max_chars: truncate content (0 = no limit).
        On failure returns ok=false with error and reason; never bypass verification pages."""
        try:
            art = await asyncio.to_thread(_fetch, url)
        except (WxFetchError, OSError) as exc:
            return _err(exc)
        return _ok(art, format, max_chars)

    @mcp.tool()
    async def parse_wechat_html(html: str, url: Optional[str] = None, format: str = "markdown",
                                max_chars: int = 40000) -> dict[str, Any]:
        """Parse a saved WeChat article page (HTML you already have) without network access."""
        try:
            art = await asyncio.to_thread(_parse, html, url or "")
        except WxFetchError as exc:
            return _err(exc, fetched=False)
        return _ok(art, format, max_chars)

    return mcp


def main() -> None:
    try:
        server = build_server()
    except ImportError:
        print("wxfetch-mcp needs the MCP Python SDK (Python 3.10+): pip install 'mcp>=1.2'", file=sys.stderr)
        sys.exit(1)
    server.run()


if __name__ == "__main__":  # pragma: no cover
    main()
