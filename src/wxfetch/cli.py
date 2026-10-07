"""Command-line interface: ``wxfetch``."""

from __future__ import annotations

import argparse
import logging
import random
import sys
import time
from pathlib import Path
from typing import List, Optional, Tuple

import requests

from . import __version__
from .errors import ArticleUnavailable, InvalidURL, VerificationRequired, WxFetchError
from .extractor import extract_article
from .fetcher import DEFAULT_PROFILES, USER_AGENTS, extract_urls, fetch_html, normalize_url
from .images import download_images
from .models import Article
from .output import slugify, to_json, to_markdown

EPILOG = """\
examples:
  wxfetch 'https://mp.weixin.qq.com/s/<article-id>'
  wxfetch 'https://mp.weixin.qq.com/s?__biz=...&mid=...&idx=...&sn=...&chksm=...'
  wxfetch 'URL1' 'URL2' -f json -o articles.json
  wxfetch -i urls.txt --out-dir out/ --download-images
  wxfetch --from-html saved_page.html -f json

Quote URLs in the shell: an unquoted & drops every parameter after it.
exit codes: 0 = all ok, 1 = at least one article failed, 2 = usage error
"""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="wxfetch",
        description="读取公开的微信公众号文章，输出干净的 Markdown / JSON。"
        " Read public WeChat Official Account articles as clean Markdown or JSON.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("urls", nargs="*", metavar="URL", help="文章链接 (short /s/xxx or long ?__biz=...)")
    p.add_argument("-i", "--input", metavar="FILE", help="从文件读取链接，每行一个；'-' 表示标准输入")
    p.add_argument("--from-html", metavar="FILE", action="append", default=[],
                   help="解析本地保存的 HTML 文件，不联网 (parse a saved page offline; repeatable)")
    p.add_argument("-f", "--format", choices=["markdown", "md", "json"], default="markdown",
                   help="输出格式 (default: markdown)")
    p.add_argument("-o", "--output", metavar="FILE", help="把所有结果写入这个文件 (default: stdout)")
    p.add_argument("--out-dir", metavar="DIR", help="每篇文章单独保存一个文件到这个目录")
    p.add_argument("--front-matter", action="store_true", help="Markdown 顶部加 YAML front matter")
    p.add_argument("--download-images", action="store_true",
                   help="下载图片到本地并改写 Markdown 里的图片链接")
    p.add_argument("--images-dir", metavar="DIR",
                   help="图片保存目录 (default: <输出位置>/<文章名>_images/)")
    p.add_argument("--ua", choices=sorted(USER_AGENTS), action="append",
                   help="只用指定的 UA，可重复，按顺序尝试 (default: ios, android, desktop)")
    p.add_argument("--retries", type=int, default=2, help="每个 UA 的网络重试次数 (default: 2)")
    p.add_argument("--timeout", type=float, default=20.0, help="单次请求超时秒数 (default: 20)")
    p.add_argument("--delay", type=float, default=2.0,
                   help="多篇文章之间的间隔秒数，带随机抖动 (default: 2.0)")
    p.add_argument("-v", "--verbose", action="count", default=0, help="显示抓取过程 (-vv 更详细)")
    p.add_argument("-V", "--version", action="version", version=f"wxfetch {__version__}")
    return p


def _collect_urls(args, parser) -> List[str]:
    urls: List[str] = []
    for u in args.urls:
        urls.extend(extract_urls(u) or [u])
    if args.input:
        text = sys.stdin.read() if args.input == "-" else Path(args.input).read_text(encoding="utf-8")
        found = extract_urls(text)
        if not found:
            parser.error(f"no mp.weixin.qq.com URLs found in {args.input}")
        urls.extend(found)
    seen, out = set(), []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _err(msg: str) -> None:
    print(f"wxfetch: {msg}", file=sys.stderr)


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.WARNING - 10 * min(args.verbose, 2),
        format="wxfetch: %(message)s",
    )
    fmt = "json" if args.format == "json" else "markdown"

    urls = _collect_urls(args, parser)
    if not urls and not args.from_html:
        parser.print_usage(sys.stderr)
        _err("请提供至少一个文章链接，或用 -i / --from-html (no input given)")
        return 2
    if args.output and args.out_dir:
        parser.error("use either -o/--output or --out-dir, not both")

    jobs: List[Tuple[str, str]] = [("html", f) for f in args.from_html] + [("url", u) for u in urls]
    profiles = tuple(args.ua) if args.ua else DEFAULT_PROFILES
    session = requests.Session()
    articles: List[Article] = []
    failures = 0

    for n, (kind, target) in enumerate(jobs):
        if kind == "url" and n > 0 and any(k == "url" for k, _ in jobs[:n]):
            time.sleep(max(0.0, args.delay) * (0.75 + random.random() / 2))
        try:
            if kind == "html":
                page = Path(target).read_text(encoding="utf-8", errors="replace")
                art = extract_article(page, url="")
                art.fetched_with = "local-file"
            else:
                normalized = normalize_url(target)  # fail fast; unwraps a pasted captcha URL
                res = fetch_html(normalized, profiles=profiles, retries=args.retries,
                                 timeout=args.timeout, session=session)
                art = extract_article(res.html, url=res.url)
                art.fetched_with = res.profile
                logging.getLogger("wxfetch").info("attempts: %s", "; ".join(res.attempts))
            warning = art.content_warning()
            if warning:
                logging.getLogger("wxfetch").warning("%s", warning)
        except InvalidURL as exc:
            _err(f"无效链接 invalid URL: {exc}")
            failures += 1
            continue
        except VerificationRequired as exc:
            _err(f"需要验证 verification required ({exc.reason}) [{target}]: {exc}")
            if exc.reason == "verification_page":
                _err("  提示：这是微信的验证页，不是文章。请在文章显示出来之后再另存为 HTML。")
            elif exc.reason != "long_link_missing_chksm":
                # missing-chksm already tells the user which link to paste; the other
                # reasons are a network / rate-limit signal.
                _err("  提示：稍后再试、换个网络，或用浏览器打开后另存为 HTML 再用 --from-html 解析。")
            if args.verbose and exc.attempts:
                _err("  attempts: " + "; ".join(exc.attempts))
            issued = getattr(getattr(exc, "captcha", None), "issued_at", None)
            if args.verbose and issued is not None:
                _err(f"  poc_token issued {issued.strftime('%Y-%m-%d %H:%M:%S')} UTC+8")
            failures += 1
            continue
        except ArticleUnavailable as exc:
            _err(f"文章不可用 article unavailable [{target}] ({exc.reason}): {exc.message}")
            failures += 1
            continue
        except (WxFetchError, OSError) as exc:
            _err(f"失败 failed [{target}]: {exc}")
            failures += 1
            continue
        articles.append(art)

    if not articles:
        return 1

    # ---- write output ------------------------------------------------------------------
    if args.out_dir:
        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        used = set()
        for art in articles:
            stem = slugify(art)
            base, k = stem, 2
            while stem in used:
                stem, k = f"{base}-{k}", k + 1
            used.add(stem)
            if args.download_images:
                img_dir = Path(args.images_dir) / stem if args.images_dir else out_dir / f"{stem}_images"
                _download(art, img_dir, out_dir, session)
            path = out_dir / f"{stem}.{'json' if fmt == 'json' else 'md'}"
            text = to_json([art], single=True) if fmt == "json" else to_markdown(art, args.front_matter)
            path.write_text(text, encoding="utf-8")
            print(str(path), file=sys.stderr)
    else:
        if args.download_images:
            base_dir = Path(args.output).parent if args.output else Path.cwd()
            for art in articles:
                stem = Path(args.output).stem if args.output and len(articles) == 1 else slugify(art)
                img_dir = (Path(args.images_dir) / stem) if args.images_dir else base_dir / f"{stem}_images"
                _download(art, img_dir, base_dir, session)
        if fmt == "json":
            text = to_json(articles, single=len(jobs) == 1)
        else:
            text = "\n\n---\n\n".join(to_markdown(a, args.front_matter) for a in articles)
        if args.output:
            Path(args.output).write_text(text, encoding="utf-8")
            print(args.output, file=sys.stderr)
        else:
            sys.stdout.write(text)
    return 1 if failures else 0


def _download(art: Article, img_dir: Path, link_base: Path, session) -> None:
    if not art.images and not art.cover_image:
        return
    n = download_images(art, img_dir, link_base=link_base, session=session)
    logging.getLogger("wxfetch").warning("saved %d image(s) to %s", n, img_dir)
