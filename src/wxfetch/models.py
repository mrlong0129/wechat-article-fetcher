"""Data model for an extracted article."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Image:
    url: str
    alt: str = ""
    local_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = {"url": self.url, "alt": self.alt}
        if self.local_path:
            d["local_path"] = self.local_path
        return d


@dataclass
class Article:
    url: str
    title: str = ""
    account_nickname: str = ""
    author: str = ""
    publish_time: Optional[str] = None  # ISO 8601 with +08:00
    publish_timestamp: Optional[int] = None
    cover_image: str = ""
    description: str = ""
    content_markdown: str = ""
    content_text: str = ""
    images: List[Image] = field(default_factory=list)
    extraction_method: str = ""
    extraction_candidates: Dict[str, int] = field(default_factory=dict)
    canonical_url: str = ""
    account_id: str = ""  # gh_xxxxxxxx
    account_alias: str = ""
    item_show_type: Optional[int] = None
    fetched_with: Optional[str] = None  # which User-Agent profile got the page

    @property
    def char_count(self) -> int:
        return len(self.content_text)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["images"] = [img.to_dict() for img in self.images]
        d["char_count"] = self.char_count
        return d
