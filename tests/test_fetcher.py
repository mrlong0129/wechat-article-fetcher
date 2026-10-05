import pytest
import requests

from wxfetch import ArticleUnavailable, FetchError, InvalidURL, VerificationRequired
from wxfetch.fetcher import USER_AGENTS, extract_urls, fetch_html, normalize_url


@pytest.mark.parametrize("raw,expected", [
    ("https://mp.weixin.qq.com/s/AbCdEfGhIjKlMnOpQrStUv", "https://mp.weixin.qq.com/s/AbCdEfGhIjKlMnOpQrStUv"),
    ("mp.weixin.qq.com/s/AbCdEfGhIjKlMnOpQrStUv", "https://mp.weixin.qq.com/s/AbCdEfGhIjKlMnOpQrStUv"),
    ("http://mp.weixin.qq.com/s/abc?nwr_flag=1#wechat_redirect", "https://mp.weixin.qq.com/s/abc"),
    ("https://mp.weixin.qq.com/s?__biz=MzAwMDAwMDAwMA==&amp;mid=1000000001&amp;idx=1&amp;sn=f8ef&amp;scene=21#wechat_redirect",
     "https://mp.weixin.qq.com/s?__biz=MzAwMDAwMDAwMA==&mid=1000000001&idx=1&sn=f8ef&scene=21"),
])
def test_normalize_url(raw, expected):
    assert normalize_url(raw) == expected


@pytest.mark.parametrize("bad", ["", "https://example.com/s/abc", "https://mp.weixin.qq.com/s",
                                 "https://mp.weixin.qq.com/s?__biz=xx"])
def test_normalize_url_rejects(bad):
    with pytest.raises(InvalidURL):
        normalize_url(bad)


def test_extract_urls_from_text():
    text = """# comment line https://mp.weixin.qq.com/s/ignored
    看看这个：https://mp.weixin.qq.com/s/AAA，还有 mp.weixin.qq.com/s/BBB
    https://mp.weixin.qq.com/s/AAA
    """
    assert extract_urls(text) == ["https://mp.weixin.qq.com/s/AAA", "mp.weixin.qq.com/s/BBB"]


class FakeResp:
    def __init__(self, text, status=200, url="https://mp.weixin.qq.com/s/x"):
        self.text = text
        self.status_code = status
        self.url = url
        self.encoding = "utf-8"


class FakeSession:
    """Returns queued responses and records the User-Agent of each request."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.uas = []
        self.headers_seen = []

    def get(self, url, headers=None, timeout=None, allow_redirects=True):
        self.uas.append(headers["User-Agent"])
        self.headers_seen.append(headers)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def no_sleep(_):
    pass


def test_falls_back_from_verify_to_next_ua(fixture_html):
    sess = FakeSession([
        FakeResp(fixture_html("verify_real.html"),
                 url="https://mp.weixin.qq.com/mp/wappoc_appmsgcaptcha?poc_token=x"),
        FakeResp(fixture_html("long_article_synthetic.html")),
    ])
    res = fetch_html("https://mp.weixin.qq.com/s/x", session=sess, sleep=no_sleep)
    assert res.profile == "android"
    assert sess.uas == [USER_AGENTS["ios"], USER_AGENTS["android"]]
    h = sess.headers_seen[0]
    assert h["Referer"] == "https://mp.weixin.qq.com/" and h["Accept-Language"].startswith("zh-CN")


def test_all_uas_verify_raises(fixture_html):
    page = fixture_html("verify_synthetic.html")
    sess = FakeSession([FakeResp(page)] * 3)
    with pytest.raises(VerificationRequired) as ei:
        fetch_html("https://mp.weixin.qq.com/s?__biz=AA==&mid=1&idx=1&sn=2", session=sess, sleep=no_sleep)
    assert len(sess.uas) == 3
    assert "短链接" in str(ei.value)  # long-link hint


def test_deleted_stops_immediately(fixture_html):
    sess = FakeSession([FakeResp(fixture_html("deleted_synthetic.html"))])
    with pytest.raises(ArticleUnavailable) as ei:
        fetch_html("https://mp.weixin.qq.com/s/x", session=sess, sleep=no_sleep)
    assert ei.value.reason == "deleted"
    assert len(sess.uas) == 1


def test_retries_network_errors_then_succeeds(fixture_html):
    sleeps = []
    sess = FakeSession([
        requests.ConnectionError("boom"),
        FakeResp("", status=503),
        FakeResp(fixture_html("long_article_synthetic.html")),
    ])
    res = fetch_html("https://mp.weixin.qq.com/s/x", session=sess, retries=2, sleep=sleeps.append)
    assert res.profile == "ios"
    assert len(sleeps) == 2 and sleeps[1] > sleeps[0] * 1.2  # exponential backoff


def test_gives_up_after_retries():
    sess = FakeSession([requests.Timeout("slow")] * 3)
    with pytest.raises(FetchError):
        fetch_html("https://mp.weixin.qq.com/s/x", session=sess, retries=0, sleep=no_sleep)
