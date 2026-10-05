"""Classify a fetched page: real article, captcha/verification page, or an error page."""

from __future__ import annotations

import re
from typing import Tuple

VERIFY_URL_MARKERS = ("wappoc_appmsgcaptcha", "secitptpage", "/mp/captcha")
VERIFY_HTML_MARKERS = ("secitptpage", "wappoc_appmsgcaptcha")

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


def is_verification(page: str, final_url: str = "") -> bool:
    if any(m in (final_url or "") for m in VERIFY_URL_MARKERS):
        return True
    if has_article(page) and 'id="js_content"' in page:
        return False
    if any(m in page for m in VERIFY_HTML_MARKERS):
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
