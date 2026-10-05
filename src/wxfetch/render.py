"""A small HTML -> Markdown / plain-text renderer tuned for WeChat article markup.

WeChat article bodies are deeply nested ``<section>``/``<span leaf>`` soup with inline
styles, lazy images (``data-src``), hidden elements and embedded widgets. Generic
converters cope, but produce noisy output; this renderer keeps what matters for reading
(headings, paragraphs, lists, bold/italic, links, images, quotes, code, simple tables)
and drops the rest.
"""

from __future__ import annotations

import re
import unicodedata
from typing import List, Optional, Tuple

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

from .models import Image

# Elements whose content is never article text.
DROP_TAGS = {
    "script", "style", "noscript", "template", "svg", "canvas", "button", "input",
    "select", "textarea", "form", "head", "title", "meta", "link",
    # WeChat widgets
    "mp-common-profile", "mp-style-type", "mp-miniprogram", "mpprofile", "mpcps",
    "mp-common-product", "mp-common-cpsad", "mp-common-poi", "qqmusic", "mpvoice",
    "mp-common-mpaudio", "mp-common-search", "mp-common-sticker",
}
BLOCK_TAGS = {
    "p", "div", "section", "article", "header", "footer", "aside", "main", "nav",
    "figure", "figcaption", "center", "address", "details", "summary", "dl", "dt", "dd",
}
HEADING_TAGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}

# Marks a line break that came from <br> (or a single newline in text posts). It survives
# nested rendering and is turned into a Markdown hard break ("two spaces + newline") at
# the very end, so that line breaks inside a paragraph render in every viewer.
BR = "\u0001"
# Indentation for list continuation / nested lists. finalize() strips leading spaces of
# every line, so indentation is carried by this marker until resolve_breaks().
INDENT = "\u0002"

_ZW_RE = re.compile("[\u200b\u200c\u200d\u2060\ufeff]")
_WS_RE = re.compile(r"[ \t\r\n\f\v\u00a0\u3000]+")


def normalize_image_url(url: str) -> str:
    url = (url or "").strip()
    if url.startswith("//"):
        url = "https:" + url
    if url.startswith("http://mmbiz.qpic.cn") or url.startswith("http://mmbiz.qlogo.cn"):
        url = "https://" + url[len("http://"):]
    return url


def _is_hidden(tag: Tag) -> bool:
    style = tag.get("style") or ""
    if "display" in style and re.search(r"display\s*:\s*none", style, re.I):
        return True
    if tag.has_attr("hidden") or tag.get("aria-hidden") == "true" and not tag.get_text(strip=True):
        return True
    return False


class _Renderer:
    def __init__(self, plain: bool):
        self.plain = plain
        self.images: List[Image] = []
        self._seen_images = set()

    # ---- entry -------------------------------------------------------------------------
    def render(self, root: Tag) -> str:
        out = finalize(self.children(root, bold=False, pre=False))
        return resolve_breaks(out)

    # ---- helpers -----------------------------------------------------------------------
    def children(self, node: Tag, bold: bool, pre: bool) -> str:
        parts = []
        for child in node.children:
            parts.append(self.node(child, bold, pre))
        return "".join(parts)

    def node(self, n, bold: bool, pre: bool) -> str:
        if isinstance(n, Comment):
            return ""
        if isinstance(n, NavigableString):
            text = _ZW_RE.sub("", str(n))
            if pre:
                return text
            return _WS_RE.sub(" ", text)
        if not isinstance(n, Tag):
            return ""

        name = (n.name or "").lower()
        if name in DROP_TAGS or _is_hidden(n):
            return ""

        if name == "br":
            return "\n" if self.plain else BR + "\n"
        if name == "img":
            return self.img(n)
        if name in HEADING_TAGS:
            return self.heading(n, HEADING_TAGS[name])
        if name in ("strong", "b"):
            return self.wrap(n, "**", bold, pre, is_bold=True)
        if name in ("em", "i"):
            return self.wrap(n, "*", bold, pre)
        if name in ("del", "s", "strike"):
            return self.wrap(n, "~~", bold, pre)
        if name == "a":
            return self.link(n, bold, pre)
        if name == "code" and not pre:
            txt = n.get_text()
            txt = _WS_RE.sub(" ", txt).strip()
            if not txt:
                return ""
            return txt if self.plain else f"`{txt}`"
        if name == "pre":
            return self.pre(n)
        if name in ("ul", "ol"):
            return self.list(n, ordered=(name == "ol"), bold=bold)
        if name == "li":  # stray <li> outside a list
            return "\n\n" + self.children(n, bold, pre).strip() + "\n\n"
        if name == "blockquote":
            return self.blockquote(n, bold)
        if name == "hr":
            return "\n\n" if self.plain else "\n\n---\n\n"
        if name == "table":
            return self.table(n)
        if name in ("iframe", "mpvideo", "mp-video", "video"):
            return self.video(n)
        if name in BLOCK_TAGS:
            inner = self.children(n, bold, pre)
            return "\n\n" + inner + "\n\n"
        # inline / unknown tags: span, font, sup, sub, u, label, ...
        return self.children(n, bold, pre)

    def wrap(self, n: Tag, marker: str, bold: bool, pre: bool, is_bold: bool = False) -> str:
        inner = self.children(n, bold or is_bold, pre)
        if self.plain or (is_bold and bold):
            return inner
        if not inner.strip():
            return inner if inner.isspace() else ""
        if "\n" in inner.strip():
            # emphasis wrapping block content: apply per non-empty line
            lines = inner.split("\n")
            return "\n".join(self._emph(line, marker) for line in lines)
        return self._emph(inner, marker)

    @staticmethod
    def _emph(text: str, marker: str) -> str:
        brk = ""
        if text.endswith(BR):
            text, brk = text[: -len(BR)], BR
        if not text.strip() or text.strip().startswith(("![", "#")):
            return text + brk
        lead = text[: len(text) - len(text.lstrip())]
        trail = text[len(text.rstrip()):]
        core = text.strip()
        # CommonMark's flanking rules mean `说**“引号”**这` does not render as bold in
        # CJK text. Moving edge punctuation outside the markers (`说“**引号**”这`) fixes it.
        i, j = 0, len(core)
        while i < j and (_is_punct(core[i]) or core[i].isspace()):
            i += 1
        while j > i and (_is_punct(core[j - 1]) or core[j - 1].isspace()):
            j -= 1
        if i == j:  # nothing but punctuation
            return text + brk
        return f"{lead}{core[:i]}{marker}{core[i:j]}{marker}{core[j:]}{trail}{brk}"

    def link(self, n: Tag, bold: bool, pre: bool) -> str:
        inner = self.children(n, bold, pre)
        href = (n.get("href") or "").strip()
        text = inner.strip()
        if self.plain or not href or href.startswith(("javascript:", "#")) or not text:
            return inner
        if text.startswith("!["):  # linked image: keep the image only
            return inner
        text = text.replace("[", "\\[").replace("]", "\\]")
        return f"[{text}]({href.replace(' ', '%20')})"

    def img(self, n: Tag) -> str:
        src = n.get("data-src") or n.get("data-original") or n.get("src") or ""
        src = normalize_image_url(src)
        if not src or src.startswith("data:") or not src.startswith("http"):
            return ""
        alt = _WS_RE.sub(" ", n.get("alt") or "").strip()
        if src not in self._seen_images:
            self._seen_images.add(src)
            self.images.append(Image(url=src, alt=alt))
        if self.plain:
            return ""
        return f"\n\n![{alt}]({src})\n\n"

    def heading(self, n: Tag, level: int) -> str:
        inner = self.children(n, True, False).replace(BR, "")
        lines = [ln.strip() for ln in inner.split("\n") if ln.strip()]
        if not lines:
            return ""
        # Images inside headings get pulled out as their own blocks.
        text_lines = [ln for ln in lines if not ln.startswith("![")]
        img_lines = [ln for ln in lines if ln.startswith("![")]
        out = ""
        if text_lines:
            text = " ".join(text_lines) if self.plain else " ".join(text_lines)
            out = text if self.plain else f"{'#' * level} {text}"
        return "\n\n" + out + ("\n\n" + "\n\n".join(img_lines) if img_lines else "") + "\n\n"

    def pre(self, n: Tag) -> str:
        codes = n.find_all("code", recursive=False)
        if len(codes) > 1:  # WeChat code-snippet: one <code> per line
            text = "\n".join(c.get_text() for c in codes)
        else:
            text = n.get_text()
        text = _ZW_RE.sub("", text).replace("\u00a0", " ").strip("\n")
        if not text.strip():
            return ""
        if self.plain:
            return "\n\n" + text + "\n\n"
        lang = (n.get("data-lang") or "").strip()
        return f"\n\n```{lang}\n{text}\n```\n\n"

    def list(self, n: Tag, ordered: bool, bold: bool) -> str:
        items = []
        idx = 1
        for li in n.find_all("li", recursive=False):
            body = finalize(self.children(li, bold, False))
            if not body:
                continue
            prefix = f"{idx}. " if ordered else "- "
            pad = INDENT * len(prefix)
            lines = body.split("\n")
            first = prefix + lines[0]
            rest = [(pad + ln) if ln else "" for ln in lines[1:]]
            items.append("\n".join([first] + rest))
            idx += 1
        if not items:
            return ""
        return "\n\n" + "\n".join(items) + "\n\n"

    def blockquote(self, n: Tag, bold: bool) -> str:
        body = finalize(self.children(n, bold, False))
        if not body:
            return ""
        if self.plain:
            return "\n\n" + body + "\n\n"
        quoted = "\n".join(("> " + ln) if ln else ">" for ln in body.split("\n"))
        return "\n\n" + quoted + "\n\n"

    def table(self, n: Tag) -> str:
        rows = []
        for tr in n.find_all("tr"):
            cells = []
            for td in tr.find_all(["td", "th"], recursive=False):
                txt = finalize(self.children(td, False, False)).replace(BR, "").replace("\n", " ").replace("|", "\\|")
                cells.append(txt)
            if any(c.strip() for c in cells):
                rows.append(cells)
        if not rows:
            return ""
        if self.plain:
            return "\n\n" + "\n".join("\t".join(r) for r in rows) + "\n\n"
        width = max(len(r) for r in rows)
        rows = [r + [""] * (width - len(r)) for r in rows]
        lines = ["| " + " | ".join(rows[0]) + " |", "|" + " --- |" * width]
        lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
        return "\n\n" + "\n".join(lines) + "\n\n"

    def video(self, n: Tag) -> str:
        src = n.get("data-src") or n.get("src") or ""
        src = normalize_image_url(src)
        if self.plain:
            return "\n\n[视频]\n\n"
        if src.startswith("http"):
            return f"\n\n[视频]({src})\n\n"
        return "\n\n[视频]\n\n"


def _is_punct(ch: str) -> bool:
    return unicodedata.category(ch)[0] in ("P", "S") and ch not in "`[]!"


def finalize(text: str) -> str:
    """Collapse whitespace and empty sections into tidy Markdown (code fences untouched)."""
    # merge adjacent emphasis runs: **a****b** -> **ab**
    text = re.sub(r"(?<=\S)\*\*\*\*(?=\S)", "", text)
    lines = []
    in_fence = False
    for line in text.split("\n"):
        if line.strip().startswith("```"):
            in_fence = not in_fence
            lines.append(line.strip())
            continue
        if in_fence:
            lines.append(line.rstrip())
            continue
        has_br = line.rstrip(" \t\u00a0\u3000").endswith(BR)
        line = line.replace(BR, "").strip(" \t\u00a0\u3000")
        # drop lines that only contain emphasis markers / quote markers
        if re.fullmatch(r"(\*\*|\*|~~|>|\s)*", line):
            line = ""
        elif has_br:
            line += BR
        lines.append(line)
    out = "\n".join(lines)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def resolve_breaks(text: str) -> str:
    """Turn BR sentinels into Markdown hard breaks when another line follows directly."""
    text = re.sub(BR + r"\n(?=[^\n])", "  \n", text)
    return text.replace(BR, "").replace(INDENT, " ")


def render_html(fragment, plain: bool = False) -> Tuple[str, List[Image]]:
    """Render a BeautifulSoup Tag (or HTML string) to Markdown (or plain text)."""
    if isinstance(fragment, str):
        fragment = BeautifulSoup(fragment, "lxml")
        fragment = fragment.body or fragment
    r = _Renderer(plain=plain)
    md = r.render(fragment)
    return md, r.images


def text_to_html(text: str) -> str:
    """Turn the newline-formatted text of WeChat 'text-only' posts into simple HTML.

    Blank lines become paragraph breaks, single newlines become ``<br>``. Inline HTML
    already present (e.g. ``<a href>`` links in ``content_noencode``) is preserved.
    """
    text = text.replace("\r\n", "\n")
    paras = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    return "".join("<p>" + p.strip("\n").replace("\n", "<br/>") + "</p>" for p in paras)
