"""wxfetch: read public WeChat Official Account (mp.weixin.qq.com) articles as clean Markdown / JSON."""

from .errors import (
    ArticleUnavailable,
    ExtractionError,
    FetchError,
    InvalidURL,
    VerificationRequired,
    WxFetchError,
)
from .extractor import extract_article
from .fetcher import fetch_html, normalize_url
from .models import Article

__version__ = "0.1.1"

__all__ = [
    "Article",
    "ArticleUnavailable",
    "ExtractionError",
    "FetchError",
    "InvalidURL",
    "VerificationRequired",
    "WxFetchError",
    "extract_article",
    "fetch_html",
    "fetch_article",
    "normalize_url",
    "__version__",
]


def fetch_article(url: str, **kwargs) -> Article:
    """Fetch a public article URL and return the extracted :class:`Article`.

    Keyword arguments are passed to :func:`wxfetch.fetcher.fetch_html`.
    """
    result = fetch_html(url, **kwargs)
    article = extract_article(result.html, url=result.url)
    article.fetched_with = result.profile
    return article
