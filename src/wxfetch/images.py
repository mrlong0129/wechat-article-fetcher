"""Download article images and rewrite Markdown links to local files.

mmbiz.qpic.cn serves images fine with no Referer or with an mp.weixin.qq.com Referer;
a *foreign* Referer gets the "此图片来自微信公众平台，未经允许不可引用" placeholder.
We send ``Referer: https://mp.weixin.qq.com/``.
"""

from __future__ import annotations

import logging
import mimetypes
import os
import time
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import parse_qs, urlsplit

import requests

from .fetcher import USER_AGENTS
from .models import Article

log = logging.getLogger("wxfetch")

_FMT_EXT = {"jpeg": ".jpg", "jpg": ".jpg", "png": ".png", "gif": ".gif", "webp": ".webp",
            "bmp": ".bmp", "svg": ".svg", "other": ".jpg"}
IMAGE_HEADERS = {
    "User-Agent": USER_AGENTS["ios"],
    "Referer": "https://mp.weixin.qq.com/",
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
}


def _guess_ext(url: str, content_type: str = "") -> str:
    q = parse_qs(urlsplit(url).query)
    fmt = (q.get("wx_fmt") or [""])[0].lower()
    if fmt in _FMT_EXT:
        return _FMT_EXT[fmt]
    if content_type:
        ext = mimetypes.guess_extension(content_type.split(";")[0].strip())
        if ext:
            return ".jpg" if ext in (".jpe", ".jpeg") else ext
    path_ext = os.path.splitext(urlsplit(url).path)[1].lower()
    return path_ext if path_ext in _FMT_EXT.values() else ".jpg"


def download_images(
    article: Article,
    images_dir: Path,
    link_base: Optional[Path] = None,
    session: Optional[requests.Session] = None,
    timeout: float = 20.0,
    delay: float = 0.2,
    include_cover: bool = True,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Save every image of ``article`` into ``images_dir`` and rewrite its Markdown.

    ``link_base`` is the directory the Markdown file will live in; links are written
    relative to it. Returns the number of images saved. Failures are logged and the
    original remote URL is kept for that image.
    """
    sess = session or requests.Session()
    images_dir = Path(images_dir)
    images_dir.mkdir(parents=True, exist_ok=True)
    link_base = Path(link_base) if link_base is not None else images_dir.parent
    saved = 0

    targets = list(article.images)
    for idx, img in enumerate(targets, 1):
        local = _fetch_one(sess, img.url, images_dir, f"{idx:03d}", timeout)
        if local is None:
            continue
        rel = os.path.relpath(local, link_base).replace(os.sep, "/")
        img.local_path = rel
        article.content_markdown = article.content_markdown.replace(f"]({img.url})", f"]({rel})")
        saved += 1
        if delay:
            sleep(delay)

    if include_cover and article.cover_image:
        local = _fetch_one(sess, article.cover_image, images_dir, "cover", timeout)
        if local is not None:
            saved += 1
    return saved


def _fetch_one(sess: requests.Session, url: str, folder: Path, stem: str, timeout: float) -> Optional[Path]:
    for attempt in range(3):
        try:
            resp = sess.get(url, headers=IMAGE_HEADERS, timeout=timeout)
            if resp.status_code == 200 and resp.content:
                ctype = resp.headers.get("Content-Type", "")
                if ctype and not ctype.startswith("image/"):
                    log.warning("not an image (%s): %s", ctype, url)
                    return None
                path = folder / f"{stem}{_guess_ext(url, ctype)}"
                path.write_bytes(resp.content)
                return path
            log.warning("image HTTP %s: %s", resp.status_code, url)
            if resp.status_code < 500 and resp.status_code != 429:
                return None
        except requests.RequestException as exc:
            log.warning("image download failed (%s): %s", exc, url)
        time.sleep(0.5 * (2 ** attempt))
    return None
