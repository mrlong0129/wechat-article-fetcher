"""Helpers for pulling values out of the inline JavaScript of a WeChat article page.

WeChat embeds the article metadata in several shapes, depending on page type and
template version, e.g.::

    var msg_title = '标题'.html(false);
    var nickname = htmlDecode("公众号名");
    var ct = "1757583599";
    window.msg_title = window.title = '...';
    window.cgiDataNew = { nick_name: '...', content_noencode: '...\\x0a...', ... };

Everything here is regex + a tiny JS string-literal decoder. We never execute JS.
"""

from __future__ import annotations

import html as _html
import re
from typing import Iterable, List, Optional

# A single- or double-quoted JS string literal (no raw newlines inside).
_SQ = r"'((?:[^'\\\n]|\\.)*)'"
_DQ = r'"((?:[^"\\\n]|\\.)*)"'

_ESCAPE_RE = re.compile(r"\\(x[0-9a-fA-F]{2}|u[0-9a-fA-F]{4}|u\{[0-9a-fA-F]+\}|.)", re.S)
_SIMPLE_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}


def decode_js_string(s: str) -> str:
    r"""Decode JS escapes: ``\n``, ``\xHH``, ``\uHHHH``, ``\'``, ``\\`` ..."""
    if "\\" not in s:
        return s

    def repl(m: "re.Match[str]") -> str:
        e = m.group(1)
        if e[0] == "x" and len(e) == 3:
            return chr(int(e[1:], 16))
        if e[0] == "u" and len(e) > 1:
            hexpart = e[2:-1] if e[1] == "{" else e[1:]
            try:
                return chr(int(hexpart, 16))
            except ValueError:
                return e
        return _SIMPLE_ESCAPES.get(e, e)

    out = _ESCAPE_RE.sub(repl, s)
    # Re-join UTF-16 surrogate pairs produced by \uD83D\uDE00 style escapes.
    try:
        out = out.encode("utf-16", "surrogatepass").decode("utf-16")
    except UnicodeError:
        pass
    return out


def _clean(value: str, html_unescape: bool) -> str:
    value = decode_js_string(value)
    if html_unescape:
        value = _html.unescape(value)
    return value


def find_js_var(page: str, names: Iterable[str], html_unescape: bool = True) -> Optional[str]:
    """Return the first non-empty string assigned to any of ``names``.

    Matches ``var NAME = '...'``, ``window.NAME = "..."``, chained assignments such as
    ``window.msg_title = window.title = '...'`` and wrappers like ``htmlDecode("...")``.
    Comparisons (``==`` / ``===``) are ignored.
    """
    for name in names:
        pat = re.compile(
            r"(?<![\w.$])(?:var\s+|let\s+|const\s+|window\.)?"
            + re.escape(name)
            + r"\s*=(?!=)\s*(?:window\.\w+\s*=(?!=)\s*)*(?:htmlDecode\(\s*)?(?:"
            + _SQ
            + "|"
            + _DQ
            + ")"
        )
        for m in pat.finditer(page):
            raw = m.group(1) if m.group(1) is not None else m.group(2)
            val = _clean(raw, html_unescape).strip()
            if val:
                return val
    return None


def extract_js_object(page: str, marker: str, opener: str = "{") -> Optional[str]:
    """Return the source text of the ``{...}`` (or ``[...]``) literal that follows ``marker``.

    Bracket matching skips over string literals, so brackets inside strings are safe.
    """
    closer = {"{": "}", "[": "]"}[opener]
    idx = page.find(marker)
    if idx < 0:
        return None
    start = page.find(opener, idx + len(marker))
    if start < 0 or start - idx > len(marker) + 20:
        return None
    depth = 0
    i = start
    n = len(page)
    quote = None
    while i < n:
        c = page[i]
        if quote:
            if c == "\\":
                i += 2
                continue
            if c == quote or c == "\n" and quote != "`":
                quote = None
        elif c in "'\"`":
            quote = c
        elif c == opener:
            depth += 1
        elif c == closer:
            depth -= 1
            if depth == 0:
                return page[start : i + 1]
        i += 1
    return None


def find_obj_key(obj_src: Optional[str], names: Iterable[str], html_unescape: bool = True) -> Optional[str]:
    """Find ``key: '...'`` (or ``"key": "..."``) inside an object-literal source string."""
    if not obj_src:
        return None
    for name in names:
        pat = re.compile(
            r"(?:^|[\s,{])[\"']?" + re.escape(name) + r"[\"']?\s*:\s*(?:" + _SQ + "|" + _DQ + ")"
        )
        for m in pat.finditer(obj_src):
            raw = m.group(1) if m.group(1) is not None else m.group(2)
            val = _clean(raw, html_unescape).strip()
            if val:
                return val
    return None


def find_number(page: str, names: Iterable[str]) -> Optional[int]:
    """Find a unix timestamp-like integer assigned to one of ``names``.

    Handles ``var ct = "1757583599";``, ``window.ct = '1757583599' || ''``,
    ``create_time: '1757583599' * 1`` and bare numbers.
    """
    for name in names:
        pat = re.compile(
            r"(?<![\w.$])(?:var\s+|window\.)?[\"']?"
            + re.escape(name)
            + r"[\"']?\s*(?:=(?!=)|:)\s*[\"']?(\d{9,11})[\"']?"
        )
        for m in pat.finditer(page):
            try:
                val = int(m.group(1))
            except ValueError:
                continue
            if val > 0:
                return val
    return None


def top_level_items(array_src: Optional[str]) -> List[str]:
    """Split a ``[ {...}, {...} ]`` literal into the source of each top-level object,
    with any nested ``{...}`` / ``[...]`` blocks blanked out (so nested keys such as
    ``watermark_info.cdn_url`` cannot be confused with the item's own keys)."""
    if not array_src:
        return []
    items: List[str] = []
    depth = 0
    quote = None
    buf: List[str] = []
    i, n = 0, len(array_src)
    while i < n:
        c = array_src[i]
        if quote:
            if depth == 2:
                buf.append(c)
            if c == "\\" and i + 1 < n:
                if depth == 2:
                    buf.append(array_src[i + 1])
                i += 2
                continue
            if c == quote:
                quote = None
        elif c in "'\"`":
            quote = c
            if depth == 2:
                buf.append(c)
        elif c in "{[":
            depth += 1
            if depth == 2:
                buf = []
        elif c in "}]":
            if depth == 2:
                items.append("".join(buf))
            depth -= 1
        elif depth == 2:
            buf.append(c)
        i += 1
    return items
