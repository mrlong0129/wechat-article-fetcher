"""Optional live tests – they hit mp.weixin.qq.com and are skipped by default.

Run with:  pytest -m live
Override the URLs with WXFETCH_LIVE_TEXT_URL / WXFETCH_LIVE_LONG_URL if the defaults
(two public articles that worked in 2026-10) are ever deleted.
"""

import os

import pytest

from wxfetch import fetch_article

pytestmark = pytest.mark.live

TEXT_URL = os.environ.get("WXFETCH_LIVE_TEXT_URL", "https://mp.weixin.qq.com/s/MiXQsJQiDbD5akEUq1XRdw")
LONG_URL = os.environ.get("WXFETCH_LIVE_LONG_URL", "https://mp.weixin.qq.com/s/-YUmnDs6ASrmxeKwfA98oQ")


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
