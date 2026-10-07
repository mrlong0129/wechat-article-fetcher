"""Classify a fetched page: real article, captcha/verification page, or an error page."""

from __future__ import annotations

import base64
import re
import struct
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
from urllib.parse import parse_qsl, unquote, urlsplit

VERIFY_URL_MARKERS = ("/mp/wappoc_appmsgcaptcha", "secitptpage", "/mp/captcha")
# ``poc_token`` alone is enough; ``TCaptcha`` only counts together with it (see is_verification).
VERIFY_HTML_MARKERS = ("secitptpage", "wappoc_appmsgcaptcha", "poc_token")

_CST = timezone(timedelta(hours=8))
_TOKEN_MIN_TS = 1577836800  # 2020-01-01 UTC


@dataclass
class CaptchaInfo:
    """What WeChat put on a verification-page URL. Informational only."""

    poc_token: str
    target_url: Optional[str] = None
    issued_at: Optional[datetime] = None  # UTC+8 when the token's timestamp is plausible

# (reason code, keywords) – matched against WeChat's own error message.
UNAVAILABLE_REASONS = [
    ("deleted", ("已被发布者删除", "已删除", "被删除", "内容已删除")),
    ("violation", ("违规", "违反", "投诉", "屏蔽", "涉嫌", "不予展示", "无法查看")),
    ("migrated", ("迁移",)),
    ("expired", ("过期", "已失效", "链接失效")),
    ("invalid_link", ("参数错误", "链接错误", "不存在")),
    ("wechat_only", ("请在微信客户端打开",)),
]

_TITLE_RE = re.compile(
    r'class="weui-msg__title[^"]*"[^>]*>\s*([^<]+?)\s*<', re.S
)
_DESC_RE = re.compile(r'class="weui-msg__desc[^"]*"[^>]*>\s*([^<]+?)\s*<', re.S)
_ARTICLE_MARKERS = ('id="js_content"', "content_noencode", "var msg_title", "window.msg_title",
                    "picture_page_info_list")


def has_article(page: str) -> bool:
    return any(m in page for m in _ARTICLE_MARKERS)


def _token_issued_at(token: str) -> Optional[datetime]:
    """Read the issue time WeChat embeds in ``poc_token`` (bytes 1–4, little-endian).

    Returns None when the token does not decode or the timestamp is outside
    2020 .. now + 1 day. Used only to explain a failure, never sent back.
    """
    if not token:
        return None
    try:
        padded = token + "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(padded)
    except (ValueError, TypeError):
        return None
    if len(raw) < 5:
        return None
    ts = struct.unpack("<I", raw[1:5])[0]
    if ts < _TOKEN_MIN_TS or ts > datetime.now(timezone.utc).timestamp() + 86400:
        return None
    return datetime.fromtimestamp(ts, _CST)


def parse_captcha_url(url: str) -> Optional[CaptchaInfo]:
    """Parse a ``/mp/wappoc_appmsgcaptcha`` (or similar) URL. None if it isn't one."""
    if not url or not any(m in url for m in VERIFY_URL_MARKERS):
        return None
    pairs = parse_qsl(urlsplit(url).query, keep_blank_values=True)
    data = {k: v for k, v in pairs}
    token = data.get("poc_token") or ""
    target = data.get("target_url") or None
    if target:
        target = unquote(target)
    return CaptchaInfo(poc_token=token, target_url=target or None, issued_at=_token_issued_at(token))


def is_verification(page: str, final_url: str = "") -> bool:
    if any(m in (final_url or "") for m in VERIFY_URL_MARKERS):
        return True
    # A page that actually has article text is not a captcha, even if a copied
    # page mentions one of the marker strings.
    if _has_real_content(page):
        return False
    if any(m in page for m in VERIFY_HTML_MARKERS):
        return True
    # TCaptcha is WeChat's widget script. On its own it is not a captcha page;
    # together with poc_token it is the page served to in-app browsers.
    if "TCaptcha" in page and "poc_token" in page:
        return True
    return len(page) < 200_000 and "环境异常" in page and ("去验证" in page or "完成验证" in page)


def classify_page(page: str, final_url: str = "") -> Tuple[str, str]:
    """Return ``(status, message)``.

    status is one of ``"article"``, ``"verify"``, ``"unavailable"`` (message is
    ``"<reason>:<wechat message>"``) or ``"unknown"``.
    """
    if not page or not page.strip():
        return "unknown", "空页面 (empty response)"
    if is_verification(page, final_url):
        return "verify", "微信返回了“环境异常 / 去验证”页面 (WeChat verification/captcha page)"

    title = _TITLE_RE.search(page)
    msg = title.group(1).strip() if title else ""
    if title and not _has_real_content(page):
        desc = _DESC_RE.search(page)
        full = msg + (("：" + desc.group(1).strip()) if desc else "")
        for reason, words in UNAVAILABLE_REASONS:
            if any(w in full for w in words):
                return "unavailable", f"{reason}:{full}"
        return "unavailable", f"unavailable:{full}"
    if has_article(page):
        return "article", ""
    return "unknown", "页面不像公众号文章 (page does not look like a WeChat article)"


def _has_real_content(page: str) -> bool:
    """True if the page carries non-empty article content (not just the empty template)."""
    m = re.search(r"var msg_title\s*=\s*(['\"])(.+?)\1", page)
    if m and m.group(2).strip():
        return True
    m = re.search(r"content_noencode\s*:\s*'([^']{5,})", page)
    if m:
        return True
    m = re.search(r'id="js_content"[^>]*>(.{0,4000})', page, re.S)
    if m and re.sub(r"<[^>]+>|\s", "", m.group(1)):
        return True
    return False
