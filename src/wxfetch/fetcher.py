"""HTTP fetching with User-Agent fallbacks, verification-page detection and polite retries."""

from __future__ import annotations

import html as _html
import logging
import random
import re
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Sequence
from urllib.parse import parse_qsl, urlsplit, urlunsplit

import requests

from .errors import ArticleUnavailable, FetchError, InvalidURL, VerificationRequired
from .pagecheck import classify_page

log = logging.getLogger("wxfetch")

USER_AGENTS = {
    # WeChat's in-app browser on iPhone – the audience these pages are built for.
    "ios": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.47(0x18002f2f) "
        "NetType/WIFI Language/zh_CN"
    ),
    # WeChat's in-app browser on Android.
    "android": (
        "Mozilla/5.0 (Linux; Android 14; Pixel 8 Build/UQ1A.240205.004; wv) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Version/4.0 Chrome/122.0.6261.120 Mobile Safari/537.36 "
        "XWEB/1220099 MMWEBSDK/20240404 MMWEBID/2307 MicroMessenger/8.0.49.2600(0x28003133) "
        "WeChat/arm64 Weixin NetType/WIFI Language/zh_CN ABI/arm64"
    ),
    # Plain desktop Chrome.
    "desktop": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/128.0.0.0 Safari/537.36"
    ),
}
DEFAULT_PROFILES = ("ios", "android", "desktop")

BASE_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
    "Referer": "https://mp.weixin.qq.com/",
    "Upgrade-Insecure-Requests": "1",
}

ALLOWED_HOSTS = {"mp.weixin.qq.com"}
URL_IN_TEXT_RE = re.compile(r"(?:https?://)?mp\.weixin\.qq\.com/[^\s<>\"'，。、）)】]+")


def normalize_url(url: str) -> str:
    """Validate and normalise an article URL.

    Accepts short links (``/s/<id>``), long links (``/s?__biz=..&mid=..&idx=..&sn=..``),
    links without scheme, ``http://`` and HTML-escaped ``&amp;``. Drops the fragment
    (``#rd`` / ``#wechat_redirect``).
    """
    raw = (url or "").strip().strip("<>\"'")
    if not raw:
        raise InvalidURL("空链接 (empty URL)")
    raw = _html.unescape(raw)
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", raw):
        raw = "https://" + raw
    parts = urlsplit(raw)
    host = (parts.hostname or "").lower()
    if host not in ALLOWED_HOSTS:
        raise InvalidURL(f"不是公众号文章链接 (not an mp.weixin.qq.com URL): {url}")
    path = parts.path or "/"
    query = parts.query
    if path.rstrip("/") in ("", "/s") and not query:
        raise InvalidURL(f"链接里缺少文章 ID (missing article id): {url}")
    if path.startswith("/s/"):
        # short link: the id is the path; query params are just share noise
        query = ""
    elif query:
        pairs = parse_qsl(query, keep_blank_values=True)
        keys = {k for k, _ in pairs}
        if "__biz" in keys and not {"mid", "sn"} <= keys and "appmsgid" not in keys:
            raise InvalidURL(f"长链接缺少 mid/sn 参数 (long URL missing mid/sn): {url}")
        # keep the query string as given (e.g. "__biz=xxx==" must not become "%3D%3D")
    return urlunsplit(("https", "mp.weixin.qq.com", path, query, ""))


def extract_urls(text: str) -> List[str]:
    """Pull every mp.weixin.qq.com link out of free-form text (one per line or not)."""
    out = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        for m in URL_IN_TEXT_RE.finditer(stripped):
            u = m.group(0).rstrip(".,;")
            if u not in out:
                out.append(u)
    return out


@dataclass
class FetchResult:
    url: str
    final_url: str
    html: str
    profile: str
    attempts: List[str] = field(default_factory=list)


def _decode(resp: requests.Response) -> str:
    if not resp.encoding or resp.encoding.lower() in ("iso-8859-1", "ascii"):
        resp.encoding = "utf-8"
    return resp.text


def fetch_html(
    url: str,
    profiles: Sequence[str] = DEFAULT_PROFILES,
    retries: int = 2,
    timeout: float = 20.0,
    backoff: float = 1.5,
    session: Optional[requests.Session] = None,
    sleep: Callable[[float], None] = time.sleep,
) -> FetchResult:
    """Fetch an article page, falling back across User-Agent profiles.

    * network errors / HTTP 429 / 5xx are retried ``retries`` times per profile with
      exponential backoff + jitter;
    * a verification ("环境异常") page moves on to the next profile;
    * a deleted / violation / invalid-link page stops immediately with
      :class:`ArticleUnavailable`.
    """
    url = normalize_url(url)
    sess = session or requests.Session()
    attempts: List[str] = []
    saw_verify = False
    last_error: Optional[str] = None

    for i, profile in enumerate(profiles):
        if profile not in USER_AGENTS:
            raise ValueError(f"unknown UA profile {profile!r}; choose from {sorted(USER_AGENTS)}")
        if i > 0:
            sleep(backoff * (0.5 + random.random()))  # be polite between fallbacks
        headers = dict(BASE_HEADERS, **{"User-Agent": USER_AGENTS[profile]})
        for attempt in range(retries + 1):
            try:
                resp = sess.get(url, headers=headers, timeout=timeout, allow_redirects=True)
            except requests.RequestException as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                attempts.append(f"{profile}#{attempt + 1}: {last_error}")
                log.info("fetch %s with %s failed: %s", url, profile, last_error)
            else:
                status = resp.status_code
                if status == 429 or status >= 500:
                    last_error = f"HTTP {status}"
                    attempts.append(f"{profile}#{attempt + 1}: HTTP {status}")
                elif status >= 400:
                    attempts.append(f"{profile}#{attempt + 1}: HTTP {status}")
                    raise FetchError(f"HTTP {status} for {url}")
                else:
                    page = _decode(resp)
                    kind, message = classify_page(page, resp.url)
                    attempts.append(f"{profile}#{attempt + 1}: {kind} ({len(page)} bytes)")
                    log.info("fetch %s with %s -> %s", url, profile, kind)
                    if kind == "article":
                        return FetchResult(url, resp.url, page, profile, attempts)
                    if kind == "unavailable":
                        reason, msg = message.split(":", 1)
                        raise ArticleUnavailable(reason, msg)
                    if kind == "verify":
                        saw_verify = True
                        last_error = message
                        break  # retrying the same UA right away won't help
                    last_error = message
                    break
            if attempt < retries:
                sleep(backoff * (2 ** attempt) * (0.75 + random.random() / 2))

    trail = "; ".join(attempts)
    if saw_verify:
        hint = ""
        if "__biz=" in url:
            hint = (" 长链接(?__biz=...)在微信客户端以外几乎总会被要求验证；请在微信里用“复制链接”"
                    "拿到 /s/xxxx 形式的短链接再试 (long ?__biz= links are almost always challenged "
                    "outside WeChat; use the short /s/<id> share link instead).")
        raise VerificationRequired(
            "所有 UA 都被微信要求验证 (WeChat demanded verification for every User-Agent)."
            f"{hint} Attempts: {trail}"
        )
    raise FetchError(f"抓取失败 (fetch failed): {last_error}. Attempts: {trail}")
