"""Formatting helpers: Markdown document, JSON, file names."""

from __future__ import annotations

import json
import re
from typing import Iterable, List

from .models import Article


def _yaml_str(value) -> str:
    return json.dumps("" if value is None else value, ensure_ascii=False)


def to_markdown(article: Article, front_matter: bool = False) -> str:
    parts: List[str] = []
    if front_matter:
        fm = [
            "---",
            f"title: {_yaml_str(article.title)}",
            f"account: {_yaml_str(article.account_nickname)}",
            f"author: {_yaml_str(article.author)}",
            f"publish_time: {_yaml_str(article.publish_time)}",
            f"url: {_yaml_str(article.canonical_url or article.url)}",
            f"cover_image: {_yaml_str(article.cover_image)}",
            f"description: {_yaml_str(article.description)}",
            f"extraction_method: {_yaml_str(article.extraction_method)}",
            "---",
        ]
        parts.append("\n".join(fm))
    parts.append(f"# {article.title}")
    meta = []
    if article.account_nickname:
        meta.append(f"公众号：{article.account_nickname}")
    if article.author and article.author != article.account_nickname:
        meta.append(f"作者：{article.author}")
    if article.publish_time:
        meta.append(f"发布时间：{article.publish_time.replace('T', ' ')}")
    lines = []
    if meta:
        lines.append("> " + " ｜ ".join(meta))
    lines.append(f"> 原文：{article.canonical_url or article.url}")
    warning = article.content_warning()
    if warning:
        lines.append(f"> {warning}")
    parts.append("\n".join(lines))
    if article.content_markdown:
        parts.append(article.content_markdown)
    return "\n\n".join(parts).rstrip() + "\n"


def to_json(articles: Iterable[Article], single: bool) -> str:
    data = [a.to_dict() for a in articles]
    payload = data[0] if single and len(data) == 1 else data
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def slugify(article: Article, max_len: int = 40) -> str:
    date = (article.publish_time or "")[:10].replace("-", "")
    title = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", article.title or "untitled")
    title = re.sub(r"\s+", "-", title.strip()).strip("-.")[:max_len].rstrip("-.") or "untitled"
    return f"{date}-{title}" if date else title
