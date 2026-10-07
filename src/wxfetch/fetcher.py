"""HTTP fetching with User-Agent fallbacks, verification-page detection and polite retries."""

from __future__ import annotations

import html as _html
import logging
import random
import re
import time
from dataclasses import dataclass, field
from typing import Callable, List, Literal, Optional, Sequence, Tuple
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

import requests

from .errors import ArticleUnavailable, FetchError, InvalidURL, VerificationRequired
from .pagecheck import VERIFY_URL_MARKERS, CaptchaInfo, classify_page, parse_captcha_url

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

# Article identity. Kept in the caller's order and spelling (``==`` stays ``==``).
# ``tempkey`` is the article's own temporary-link credential, not a login session.
_KEEP_QUERY_KEYS = {
    "__biz", "mid", "idx", "sn", "chksm", "scene", "appmsgid", "itemidx",
    "sign", "src", "timestamp", "ver", "signature", "new", "tempkey",
}
# Login-session and one-request noise. Never forwarded.
_DROP_QUERY_KEYS = {
    "key", "pass_ticket", "uin", "exportkey", "acctmode", "devicetype",
    "version", "lang", "ascene", "clicktime", "enterid", "sessionid",
    "winzoom", "wx_header", "poc_token", "nwr_flag", "from", "isappinstalled",
}

_CAPTCHA_PATHS = ("/mp/wappoc_appmsgcaptcha", "/mp/captcha")
_ARTICLE_QUERY_PATHS = ("/s", "/mp/appmsg/show")
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_MAX_REDIRECTS = 5

LinkKind = Literal["short", "long", "long_no_chksm", "temp", "other"]

_MISSING_CHKS_MSG = (
    "长链接缺少 chksm 参数，微信对这类链接一律要求验证。请使用完整的原始链接（保留 &chksm=…），"
    "或在微信里「复制链接」拿 /s/<id> 短链接。"
)
_ALL_PROFILES_MSG = (
    "所有访问方式都被要求验证，更像是当前网络或请求频率被限制。"
    "请稍后再试 / 换个网络 / 在浏览器打开后另存为 HTML 用 --from-html。"
)
_QUOTE_HINT = (
    "如果你在 shell 里没给链接加引号，& 后面的参数会被截掉，请用 '...' 包住链接 "
    "(quote the URL: an unquoted & truncates it)"
)


def _query_pairs(query: str) -> List[Tuple[str, str]]:
    """Split a query without decoding, so ``==`` and ``+`` keep their spelling."""
    pairs: List[Tuple[str, str]] = []
    if not query:
        return pairs
    for part in query.split("&"):
        if not part:
            continue
        if "=" in part:
            key, value = part.split("=", 1)
        else:
            key, value = part, ""
        pairs.append((key, value))
    return pairs


def _is_captcha_path(path: str) -> bool:
    norm = (path or "/").rstrip("/").lower() or "/"
    return norm in _CAPTCHA_PATHS


def _is_verify_url(url: str) -> bool:
    return any(marker in (url or "") for marker in VERIFY_URL_MARKERS)


def normalize_url(url: str, _depth: int = 0) -> str:
    """Validate and normalise an article URL.

    Accepts short links (``/s/<id>``), long links (``/s?__biz=..&mid=..&idx=..&sn=..``),
    ``/mp/appmsg/show?...``, links without a scheme, ``http://`` and HTML-escaped
    ``&amp;``. Drops the fragment (``#rd`` / ``#wechat_redirect``).

    A pasted verification-page URL (``/mp/wappoc_appmsgcaptcha?poc_token=…&target_url=…``)
    is unwrapped to ``target_url``. ``poc_token`` is never sent back. Login-session
    parameters (``key``, ``pass_ticket``, ``uin``, ``exportkey``, …) are stripped;
    a real ``chksm`` the caller pasted is kept. Nothing is invented.
    """
    raw = (url or "").strip().strip("<>\"'")
    if not raw:
        raise InvalidURL("空链接 (empty URL)")
    if _depth > 3:
        raise InvalidURL("验证页链接嵌套过深 (captcha URL nested too deeply)")
    raw = _html.unescape(raw)
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", raw):
        raw = "https://" + raw
    parts = urlsplit(raw)
    host = (parts.hostname or "").lower()
    if host not in ALLOWED_HOSTS:
        raise InvalidURL(f"不是公众号文章链接 (not an mp.weixin.qq.com URL): {url}")
    path = parts.path or "/"
    pairs = _query_pairs(parts.query)

    if _is_captcha_path(path):
        target = next((value for key, value in pairs if key == "target_url" and value), None)
        if not target:
            raise InvalidURL(
                "这是微信「环境异常」验证页的地址，不是文章链接；请粘贴原始文章链接 "
                "(this is WeChat's verification page, not an article link)"
            )
        log.info("input was WeChat's verification page; using its target_url")
        return normalize_url(unquote(target), _depth=_depth + 1)

    norm_path = path.rstrip("/") or "/"
    if path.startswith("/s/") and norm_path != "/s":
        return urlunsplit(("https", "mp.weixin.qq.com", norm_path, "", ""))

    if norm_path in _ARTICLE_QUERY_PATHS:
        if not pairs:
            raise InvalidURL(f"链接里缺少文章 ID (missing article id): {url}")
        kept = [(key, value) for key, value in pairs
                if key in _KEEP_QUERY_KEYS and key not in _DROP_QUERY_KEYS]
        keys = {key for key, _ in kept}
        if "__biz" in keys and not {"mid", "sn"} <= keys and "appmsgid" not in keys and "tempkey" not in keys:
            raise InvalidURL(
                f"长链接缺少 mid/sn 参数 (long URL missing mid/sn): {url}. {_QUOTE_HINT}"
            )
        if not kept:
            raise InvalidURL(f"链接里缺少文章 ID (missing article id): {url}")
        query = "&".join(f"{key}={value}" for key, value in kept)
        return urlunsplit(("https", "mp.weixin.qq.com", norm_path, query, ""))

    raise InvalidURL(f"不是文章链接 (not an article URL): {url}")


def link_kind(url: str) -> LinkKind:
    """Classify an article URL after normalisation.

    ``long_no_chksm`` is a ``/s`` or ``/mp/appmsg/show`` link that has ``__biz``
    and no ``chksm``. WeChat challenges that form for every client. A ``tempkey``
    link is ``temp`` instead: it is a different URL form, and a challenge on it
    is not known to be independent of the User-Agent.
    """
    normalized = normalize_url(url)
    parts = urlsplit(normalized)
    path = parts.path.rstrip("/") or "/"
    keys = {key for key, _ in _query_pairs(parts.query)}
    if path.startswith("/s/") and path != "/s":
        return "short"
    if "tempkey" in keys:
        return "temp"
    if path in _ARTICLE_QUERY_PATHS:
        if "__biz" in keys and "chksm" not in keys:
            return "long_no_chksm"
        if "__biz" in keys and "chksm" in keys:
            return "long"
        if keys & {"signature", "sign", "timestamp", "src"}:
            return "temp"
    return "other"


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


@dataclass
class _Page:
    kind: str
    message: str = ""
    html: str = ""
    final_url: str = ""
    captcha: Optional[CaptchaInfo] = None


def _decode(resp: requests.Response) -> str:
    if not resp.encoding or resp.encoding.lower() in ("iso-8859-1", "ascii"):
        resp.encoding = "utf-8"
    return resp.text


def _location(resp) -> str:
    headers = getattr(resp, "headers", None) or {}
    getter = getattr(headers, "get", None)
    if getter is None:
        return ""
    value = getter("Location") or getter("location") or ""
    return value


def _allowed_host(url: str) -> bool:
    return (urlsplit(url).hostname or "").lower() in ALLOWED_HOSTS


def _drop_poc_sid(sess) -> None:
    """Drop the captcha cookie before the next profile. No effect was observed; hygiene only."""
    cookies = getattr(sess, "cookies", None)
    if cookies is None:
        return
    # requests stores the Domain attribute with or without a leading dot.
    for domain in (".mp.weixin.qq.com", "mp.weixin.qq.com"):
        try:
            cookies.clear(domain=domain, path="/", name="poc_sid")
        except KeyError:
            pass


def _fetch_following_redirects(sess, url: str, headers: dict, timeout: float) -> _Page:
    """GET ``url`` and follow up to 5 same-host redirects.

    A ``Location`` that is WeChat's verification page is classified as ``verify``
    without requesting that page. A redirect to any other host is an error.
    """
    current = url
    hops = 0
    while True:
        resp = sess.get(current, headers=headers, timeout=timeout, allow_redirects=False)
        loc = _location(resp)
        if loc and _is_verify_url(loc):
            absolute = urljoin(current, loc)
            return _Page(
                kind="verify",
                message="微信返回了“环境异常 / 去验证”页面 (WeChat verification/captcha page)",
                final_url=absolute,
                captcha=parse_captcha_url(absolute),
            )
        status = getattr(resp, "status_code", 200)
        if status in _REDIRECT_STATUSES:
            if not loc:
                raise FetchError(f"重定向缺少 Location (redirect without Location) for {current}")
            if hops >= _MAX_REDIRECTS:
                raise FetchError(f"重定向次数过多 (too many redirects) for {url}")
            nxt = urljoin(current, loc)
            if not _allowed_host(nxt):
                host = (urlsplit(nxt).hostname or "").lower() or nxt
                raise FetchError(f"重定向到了意外的站点 (redirected off mp.weixin.qq.com): {host}")
            current = nxt
            hops += 1
            continue
        if status == 429 or status >= 500:
            return _Page(kind="retry", message=f"HTTP {status}", final_url=current)
        if status >= 400:
            raise FetchError(f"HTTP {status} for {current}")
        page = _decode(resp)
        final = getattr(resp, "url", None) or current
        if _is_verify_url(final):
            return _Page(
                kind="verify",
                message="微信返回了“环境异常 / 去验证”页面 (WeChat verification/captcha page)",
                html=page,
                final_url=final,
                captcha=parse_captcha_url(final),
            )
        kind, message = classify_page(page, final)
        return _Page(
            kind=kind,
            message=message,
            html=page,
            final_url=final,
            captcha=parse_captcha_url(final) if kind == "verify" else None,
        )


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
    * a verification page moves on to the next profile, except a long link that
      has no ``chksm``: that URL form is challenged for every client, so the first
      verification response stops the fetch (one request, no further profiles);
    * a deleted / violation / invalid-link page stops immediately with
      :class:`ArticleUnavailable`.

    Switching User-Agent only helps when the challenge depends on the client.
    It does not, and must not, add a ``chksm`` or any other parameter.
    """
    url = normalize_url(url)
    kind_of_link = link_kind(url)
    sess = session or requests.Session()
    attempts: List[str] = []
    saw_verify = False
    captcha_info: Optional[CaptchaInfo] = None
    stop_profiles = False
    last_error: Optional[str] = None

    for i, profile in enumerate(profiles):
        if profile not in USER_AGENTS:
            raise ValueError(f"unknown UA profile {profile!r}; choose from {sorted(USER_AGENTS)}")
        if i > 0:
            _drop_poc_sid(sess)
            sleep(backoff * (0.5 + random.random()))  # be polite between fallbacks
        headers = dict(BASE_HEADERS, **{"User-Agent": USER_AGENTS[profile]})
        for attempt in range(retries + 1):
            try:
                page = _fetch_following_redirects(sess, url, headers, timeout)
            except requests.RequestException as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                attempts.append(f"{profile}#{attempt + 1}: {last_error}")
                log.info("fetch %s with %s failed: %s", url, profile, last_error)
            else:
                if page.kind == "retry":
                    last_error = page.message
                    attempts.append(f"{profile}#{attempt + 1}: {page.message}")
                elif page.kind == "article":
                    attempts.append(f"{profile}#{attempt + 1}: article ({len(page.html)} bytes)")
                    log.info("fetch %s with %s -> article", url, profile)
                    return FetchResult(url, page.final_url, page.html, profile, attempts)
                elif page.kind == "unavailable":
                    attempts.append(f"{profile}#{attempt + 1}: unavailable ({len(page.html)} bytes)")
                    reason, msg = page.message.split(":", 1)
                    raise ArticleUnavailable(reason, msg)
                elif page.kind == "verify":
                    saw_verify = True
                    if page.captcha is not None:
                        captcha_info = page.captcha
                    label = "verify (redirect)" if not page.html else f"verify ({len(page.html)} bytes)"
                    attempts.append(f"{profile}#{attempt + 1}: {label}")
                    log.info("fetch %s with %s -> verify", url, profile)
                    last_error = page.message
                    # A missing chksm is a property of the URL. Every profile gets the
                    # same challenge, so retrying other User-Agents only adds noise.
                    if kind_of_link == "long_no_chksm":
                        stop_profiles = True
                    break
                else:
                    attempts.append(f"{profile}#{attempt + 1}: {page.kind} ({len(page.html)} bytes)")
                    last_error = page.message
                    break
            if attempt < retries:
                sleep(backoff * (2 ** attempt) * (0.75 + random.random() / 2))
        if stop_profiles:
            break

    trail = "; ".join(attempts)
    if saw_verify:
        if kind_of_link == "long_no_chksm":
            reason = "long_link_missing_chksm"
            message = _MISSING_CHKS_MSG
        else:
            reason = "all_profiles_challenged"
            message = _ALL_PROFILES_MSG
        raise VerificationRequired(
            message,
            reason=reason,
            link_kind=kind_of_link,
            captcha=captcha_info,
            attempts=attempts,
        )
    raise FetchError(f"抓取失败 (fetch failed): {last_error}. Attempts: {trail}")
