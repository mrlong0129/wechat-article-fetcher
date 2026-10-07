"""Optional live tests – they hit mp.weixin.qq.com and are skipped by default.

Run with:  pytest -m live
Override the URLs with WXFETCH_LIVE_TEXT_URL / WXFETCH_LIVE_LONG_URL /
WXFETCH_LIVE_LONG_CHKSM_URL / WXFETCH_LIVE_LONG_NOCHKSM_URL if the defaults
(public articles that worked on 2026-10-07) are ever deleted.
"""

import os

import pytest

from wxfetch import VerificationRequired, fetch_article

pytestmark = pytest.mark.live

TEXT_URL = os.environ.get("WXFETCH_LIVE_TEXT_URL", "https://mp.weixin.qq.com/s/MiXQsJQiDbD5akEUq1XRdw")
LONG_URL = os.environ.get("WXFETCH_LIVE_LONG_URL", "https://mp.weixin.qq.com/s/-YUmnDs6ASrmxeKwfA98oQ")
# A real long link that still has its chksm, and the same link with chksm removed.
# The chksm below is the one the article was published with; the test must not invent one.
_LONG_WITH_CHKSM = (
    "https://mp.weixin.qq.com/s?__biz=MzkzODIxNjA4MA==&mid=2247493427&idx=5"
    "&sn=dd84ee2df73fc1a06785c105dd1b2b80"
    "&chksm=c28138ccf5f6b1da445255edc9ea9171fa21a52a1e15a98cd2a2ae3ed26d5f2f548bdf4e8a5c"
    "&scene=18"
)
_LONG_NO_CHKSM = (
    "https://mp.weixin.qq.com/s?__biz=MzkzODIxNjA4MA==&mid=2247493427&idx=5"
    "&sn=dd84ee2df73fc1a06785c105dd1b2b80&scene=18"
)
LONG_CHKSM_URL = os.environ.get("WXFETCH_LIVE_LONG_CHKSM_URL", _LONG_WITH_CHKSM)
LONG_NOCHKSM_URL = os.environ.get("WXFETCH_LIVE_LONG_NOCHKSM_URL", _LONG_NO_CHKSM)


def test_live_text_post():
    art = fetch_article(TEXT_URL)
    assert art.extraction_method in ("js_content_noencode", "og_meta", "js_content")
    assert art.account_nickname and art.publish_time
    assert len(art.content_text) > 100


def test_live_long_article():
    art = fetch_article(LONG_URL)
    assert art.extraction_method == "js_content"
    assert art.account_nickname and art.publish_time
    assert len(art.content_text) > 1000
    assert len(art.images) >= 3


def test_live_long_link_with_chksm():
    art = fetch_article(LONG_CHKSM_URL)
    assert art.account_nickname
    assert art.content_text.strip() or art.images


def test_live_long_link_missing_chksm():
    with pytest.raises(VerificationRequired) as ei:
        fetch_article(LONG_NOCHKSM_URL)
    assert ei.value.reason == "long_link_missing_chksm"
    assert ei.value.attempts
    assert all(item.startswith("ios#") for item in ei.value.attempts)
