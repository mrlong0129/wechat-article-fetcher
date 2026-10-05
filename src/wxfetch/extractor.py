"""Turn a WeChat article HTML page into an :class:`~wxfetch.models.Article`.

Content candidates, tried in this order (and then the richest one wins):

1. ``js_content``       – the ``<div id="js_content">`` body, parsed with a real HTML
                           parser (normal long-form articles).
2. ``js_content_noencode`` – the ``content_noencode`` / ``text_page_info`` string in
                           ``window.cgiDataNew`` (short "text-only" / 图文短内容 posts,
                           item_show_type 10), which keeps inline links.
3. ``picture_page``     – image-gallery posts (item_show_type 8): the picture list plus
                           any text.
4. ``og_meta``          – ``og:title`` / ``og:description`` / ``twitter:title`` meta tags.
                           For short text-only posts WeChat puts the *whole* text here
                           with literal ``\\n`` escapes.
"""

from __future__ import annotations

import html as _html
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from . import jsvars
from .errors import ArticleUnavailable, ExtractionError, VerificationRequired
from .models import Article, Image
from .pagecheck import classify_page
from .render import normalize_image_url, render_html, text_to_html

CST = timezone(timedelta(hours=8), name="Asia/Shanghai")

# Priority used to break ties between candidates of similar richness.
METHOD_PRIORITY = ["js_content", "js_content_noencode", "picture_page", "og_meta"]


def ts_to_iso(ts: Optional[int]) -> Optional[str]:
    if not ts:
        return None
    return datetime.fromtimestamp(ts, CST).isoformat()


def _meta(soup: BeautifulSoup, *keys: str) -> str:
    for key in keys:
        tag = soup.find("meta", attrs={"property": key}) or soup.find("meta", attrs={"name": key})
        if tag and tag.get("content"):
            val = jsvars.decode_js_string(tag["content"]).strip()
            if val:
                return val
    return ""


def _text_of(soup: BeautifulSoup, selector: str) -> str:
    el = soup.select_one(selector)
    if not el:
        return ""
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip()


def _strip_tracking(url: str) -> str:
    """Drop WeChat's per-share noise params (nwr_flag, scene, ...) from canonical links."""
    if not url:
        return url
    parts = urlsplit(url)
    keep = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if k in ("__biz", "mid", "idx", "sn")]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(keep), ""))


def _short_title(text: str, limit: int = 60) -> str:
    """Derive a readable title from the body of a title-less text post."""
    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    m = re.search(r"[。！？!?]", first)
    if m and m.end() <= limit:
        return first[: m.end()]
    if len(first) <= limit:
        return first
    cut = first[:limit]
    m2 = None
    for m2 in re.finditer(r"[，,；;：:]", cut):
        pass
    if m2 and m2.end() >= limit // 2:
        cut = first[: m2.start()]
    return cut + "…"


def _plain_len(text: str) -> int:
    return len(re.sub(r"\s+", "", text or ""))


# --------------------------------------------------------------------------------------
# candidates
# --------------------------------------------------------------------------------------
class _Candidate:
    def __init__(self, method: str, markdown: str, text: str, images: List[Image]):
        self.method = method
        self.markdown = markdown
        self.text = text
        self.images = images

    @property
    def score(self) -> int:
        return _plain_len(self.text) + 20 * len(self.images)


def _from_js_content(soup: BeautifulSoup) -> Optional[_Candidate]:
    node = soup.find(id="js_content")
    if node is None:
        return None
    md, images = render_html(node)
    text, _ = render_html(node, plain=True)
    if not text.strip() and not images:
        return None
    return _Candidate("js_content", md, text, images)


def _from_noencode(cgi: Optional[str]) -> Optional[_Candidate]:
    if not cgi:
        return None
    text_page = jsvars.extract_js_object(cgi, "text_page_info")
    raw = (
        jsvars.find_obj_key(text_page, ["content_noencode"], html_unescape=False)
        or jsvars.find_obj_key(cgi, ["content_noencode"], html_unescape=False)
    )
    if not raw:
        content = jsvars.find_obj_key(text_page, ["content"], html_unescape=False)
        if content:
            raw = _html.unescape(content)  # this variant is entity-encoded HTML
    if not raw or not raw.strip():
        return None
    frag = text_to_html(raw)
    md, images = render_html(frag)
    text, _ = render_html(frag, plain=True)
    if not text.strip():
        return None
    return _Candidate("js_content_noencode", md, text, images)


def _picture_urls(cgi: Optional[str]) -> List[str]:
    block = jsvars.extract_js_object(cgi or "", "picture_page_info_list", opener="[")
    urls: List[str] = []
    for item in jsvars.top_level_items(block):
        um = re.search(r"cdn_url\s*:\s*'((?:[^'\\]|\\.)*)'", item)
        if not um:
            continue
        u = jsvars.decode_js_string(um.group(1))
        for _ in range(3):  # values are sometimes entity-encoded more than once
            u = _html.unescape(u)
        u = normalize_image_url(u)
        if u.startswith("http") and u not in urls:
            urls.append(u)
    return urls


def _from_picture_page(cgi: Optional[str], text_cand: Optional[_Candidate]) -> Optional[_Candidate]:
    """Image-gallery posts (item_show_type 8): text (if any) followed by the pictures."""
    if not cgi:
        return None
    urls = _picture_urls(cgi)
    if not urls:
        return None
    images = [Image(url=u) for u in urls]
    if text_cand is not None:
        md, text = text_cand.markdown, text_cand.text
    else:
        text = jsvars.find_obj_key(cgi, ["desc"]) or ""
        md = text
    md = "\n\n".join([p for p in [md] if p] + [f"![]({u})" for u in urls])
    return _Candidate("picture_page", md, text, images)


def _from_og(soup: BeautifulSoup) -> Optional[_Candidate]:
    title = _meta(soup, "og:title", "twitter:title")
    desc = _meta(soup, "og:description", "twitter:description", "description")
    body = title if _plain_len(title) >= _plain_len(desc) else desc
    if not body:
        return None
    frag = text_to_html(_html.escape(body))
    md, _ = render_html(frag)
    text, _ = render_html(frag, plain=True)
    return _Candidate("og_meta", md, text, [])


def _pick(cands: List[_Candidate]) -> _Candidate:
    best_score = max(c.score for c in cands)
    # Prefer the most structured source when it is at least ~85% as rich as the best.
    for method in METHOD_PRIORITY:
        for c in cands:
            if c.method == method and c.score >= 0.85 * best_score:
                return c
    return max(cands, key=lambda c: c.score)


# --------------------------------------------------------------------------------------
# main entry
# --------------------------------------------------------------------------------------
def extract_article(page: str, url: str = "") -> Article:
    """Extract an :class:`Article` from raw page HTML.

    Raises :class:`VerificationRequired`, :class:`ArticleUnavailable` or
    :class:`ExtractionError` when the page is not a readable article.
    """
    status, message = classify_page(page)
    if status == "verify":
        raise VerificationRequired(message)
    if status == "unavailable":
        reason, msg = message.split(":", 1)
        raise ArticleUnavailable(reason, msg)

    soup = BeautifulSoup(page, "lxml")
    cgi = jsvars.extract_js_object(page, "window.cgiDataNew") or jsvars.extract_js_object(page, "cgiDataNew =")

    def js(*names: str) -> str:
        return jsvars.find_js_var(page, names) or jsvars.find_obj_key(cgi, names) or ""

    art = Article(url=url)

    # ---- metadata (first non-empty source wins) ----------------------------------------
    art.title = (
        jsvars.find_js_var(page, ["msg_title"])
        or _text_of(soup, "#activity-name")
        or _text_of(soup, "h1.rich_media_title")
        or jsvars.find_obj_key(cgi, ["title"])
        or _meta(soup, "og:title", "twitter:title")
        or _text_of(soup, "title")
    )
    art.account_nickname = (
        jsvars.find_js_var(page, ["nickname"])
        or jsvars.find_obj_key(cgi, ["nick_name", "nickname"])
        or _text_of(soup, "#js_name")
        or _text_of(soup, ".wx_follow_nickname")
        or _text_of(soup, ".profile_nickname")
    )
    art.author = (
        _meta(soup, "author", "og:article:author")
        or jsvars.find_js_var(page, ["author"])
        or jsvars.find_obj_key(cgi, ["author"])
        or _text_of(soup, "#js_author_name_text")
        or _text_of(soup, "#js_author_name")
    )
    ts = (
        jsvars.find_number(page, ["ct", "create_time", "ori_create_time", "ori_send_time", "publish_time"])
    )
    art.publish_timestamp = ts
    art.publish_time = ts_to_iso(ts)
    if not art.publish_time:
        human = js("create_time") or _text_of(soup, "#publish_time")
        m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})(?:\s+(\d{1,2}):(\d{2}))?", human or "")
        if m:
            y, mo, d, hh, mm = (int(x) if x else 0 for x in m.groups())
            dt = datetime(y, mo, d, hh, mm, tzinfo=CST)
            art.publish_time = dt.isoformat()
            art.publish_timestamp = int(dt.timestamp())
    art.cover_image = normalize_image_url(
        jsvars.find_js_var(page, ["msg_cdn_url", "cdn_url_235_1", "cdn_url_1_1"])
        or jsvars.find_obj_key(cgi, ["cdn_url", "cdn_url_235_1", "cdn_url_1_1"])
        or _meta(soup, "og:image", "twitter:image")
    )
    art.description = (
        jsvars.find_js_var(page, ["msg_desc"])
        or jsvars.find_obj_key(cgi, ["desc"])
        or _meta(soup, "og:description", "description")
    )
    art.canonical_url = _strip_tracking(
        jsvars.find_js_var(page, ["msg_link"])
        or jsvars.find_obj_key(cgi, ["link"])
        or _meta(soup, "og:url")
    )
    art.account_id = js("user_name")
    art.account_alias = jsvars.find_obj_key(cgi, ["alias"]) or ""
    m = re.search(r"item_show_type\s*[=:]\s*['\"]?(\d+)", page)
    art.item_show_type = int(m.group(1)) if m else None

    # ---- content ----------------------------------------------------------------------
    noencode = _from_noencode(cgi)
    cands = [c for c in (
        _from_js_content(soup),
        noencode,
        _from_picture_page(cgi, noencode),
        _from_og(soup),
    ) if c is not None]
    if not cands:
        raise ExtractionError("页面里没找到正文 (no article content found in page)")

    best = _pick(cands)
    art.extraction_method = best.method
    art.extraction_candidates = {c.method: _plain_len(c.text) for c in cands}
    art.content_markdown = best.markdown
    art.content_text = best.text
    art.images = best.images

    # Text-only posts have no real title: WeChat copies the whole body into it.
    body_len = _plain_len(art.content_text)
    if art.title and ("\n" in art.title or (len(art.title) > 120 and body_len and
                                            _plain_len(art.title) >= 0.6 * body_len)):
        art.title = _short_title(art.title)
    if not art.title:
        art.title = _short_title(art.content_text) or "(无标题)"
    if art.description and _plain_len(art.description) > 300 and art.description[:50] in art.content_text:
        art.description = art.description[:120].rstrip() + "…"
    return art
