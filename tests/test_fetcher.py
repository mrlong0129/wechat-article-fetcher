import pytest
import requests

from wxfetch import ArticleUnavailable, FetchError, InvalidURL, VerificationRequired
from wxfetch.fetcher import USER_AGENTS, extract_urls, fetch_html, link_kind, normalize_url


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
    def __init__(self, text, status=200, url="https://mp.weixin.qq.com/s/x", headers=None):
        self.text = text
        self.status_code = status
        self.url = url
        self.encoding = "utf-8"
        self.headers = headers or {}


class FakeSession:
    """Returns queued responses and records the User-Agent of each request."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.uas = []
        self.headers_seen = []
        self.urls = []
        self.allow_redirects = []
        self.cookies = None

    def get(self, url, headers=None, timeout=None, allow_redirects=True):
        self.urls.append(url)
        self.allow_redirects.append(allow_redirects)
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
        fetch_html("https://mp.weixin.qq.com/s/ExampleShort01", session=sess, sleep=no_sleep)
    assert len(sess.uas) == 3
    assert ei.value.reason == "all_profiles_challenged"
    assert ei.value.link_kind == "short"
    assert "chksm" not in str(ei.value)


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


_CAPTCHA = "https://mp.weixin.qq.com/mp/wappoc_appmsgcaptcha?poc_token=HAAAAAAA&target_url="


def test_normalize_unwraps_captcha_short_link():
    raw = _CAPTCHA + "https%3A%2F%2Fmp.weixin.qq.com%2Fs%2FAbC"
    assert normalize_url(raw) == "https://mp.weixin.qq.com/s/AbC"
    assert "poc_token" not in normalize_url(raw)


def test_normalize_unwraps_encoded_long_target():
    from urllib.parse import quote
    target = ("https://mp.weixin.qq.com/s?__biz=MzAwMDAwMDAwMA==&mid=1&idx=1"
              "&sn=f8ef&chksm=abc%2Bdef&scene=21")
    out = normalize_url(_CAPTCHA + quote(target, safe=""))
    assert out == target
    assert "__biz=MzAwMDAwMDAwMA==" in out
    assert "chksm=abc%2Bdef" in out
    assert "poc_token" not in out
    assert "wappoc" not in out


def test_captcha_url_without_target_is_rejected():
    with pytest.raises(InvalidURL, match="环境异常"):
        normalize_url("https://mp.weixin.qq.com/mp/wappoc_appmsgcaptcha?poc_token=HAAAAAAA")


def test_non_article_path_is_rejected():
    with pytest.raises(InvalidURL, match="不是文章链接"):
        normalize_url("https://mp.weixin.qq.com/mp/profile_ext?action=home&__biz=xx")


def test_session_params_stripped_chksm_kept():
    raw = ("https://mp.weixin.qq.com/s?__biz=MzAw==&mid=1&idx=1&sn=abc&chksm=def"
           "&scene=18&key=SECRET&pass_ticket=PT&uin=UIN&exportkey=EK&poc_token=P&nwr_flag=1")
    out = normalize_url(raw)
    assert out == "https://mp.weixin.qq.com/s?__biz=MzAw==&mid=1&idx=1&sn=abc&chksm=def&scene=18"
    for dropped in ("key=", "pass_ticket", "uin=", "exportkey", "poc_token", "SECRET"):
        assert dropped not in out


def test_link_kind_values():
    assert link_kind("https://mp.weixin.qq.com/s/AbC") == "short"
    assert link_kind("https://mp.weixin.qq.com/s?__biz=AA==&mid=1&idx=1&sn=2&chksm=zz&scene=18") == "long"
    assert link_kind("https://mp.weixin.qq.com/s?__biz=AA==&mid=1&idx=1&sn=2") == "long_no_chksm"
    assert link_kind("https://mp.weixin.qq.com/mp/appmsg/show?__biz=AA==&mid=1&idx=1&sn=2") == "long_no_chksm"
    assert link_kind("https://mp.weixin.qq.com/s?src=11&timestamp=1710000000&ver=1&signature=abc") == "temp"
    assert link_kind("https://mp.weixin.qq.com/s?__biz=AA==&tempkey=abc") == "temp"


def test_missing_mid_sn_mentions_shell_quoting():
    with pytest.raises(InvalidURL) as ei:
        normalize_url("https://mp.weixin.qq.com/s?__biz=xx")
    text = str(ei.value)
    assert "引号" in text and "quote" in text


def _captcha_redirect(token="HAAAAAAA"):
    return FakeResp(
        "",
        status=302,
        headers={"Location": f"https://mp.weixin.qq.com/mp/wappoc_appmsgcaptcha?poc_token={token}&target_url=https%3A%2F%2Fmp.weixin.qq.com%2Fs%2Fx"},
    )


def test_redirect_to_captcha_is_not_fetched(fixture_html):
    sess = FakeSession([
        _captcha_redirect(),
        FakeResp(fixture_html("long_article_synthetic.html")),
    ])
    res = fetch_html("https://mp.weixin.qq.com/s/AbC", session=sess, sleep=no_sleep)
    assert res.profile == "android"
    assert len(sess.urls) == 2
    assert all(flag is False for flag in sess.allow_redirects)
    assert all("wappoc_appmsgcaptcha" not in u for u in sess.urls)
    assert all(ua in USER_AGENTS.values() for ua in sess.uas)


def test_redirect_chain_to_article(fixture_html):
    sess = FakeSession([
        FakeResp("", status=302, headers={"Location": "https://mp.weixin.qq.com/s/AbC?nwr_flag=1"}),
        FakeResp(fixture_html("long_article_synthetic.html"), url="https://mp.weixin.qq.com/s/AbC?nwr_flag=1"),
    ])
    res = fetch_html("https://mp.weixin.qq.com/s/AbC", session=sess, sleep=no_sleep)
    assert res.profile == "ios"
    assert sess.urls == [
        "https://mp.weixin.qq.com/s/AbC",
        "https://mp.weixin.qq.com/s/AbC?nwr_flag=1",
    ]


def test_off_host_redirect_is_fetch_error():
    sess = FakeSession([FakeResp("", status=302, headers={"Location": "https://evil.example/phish"})])
    with pytest.raises(FetchError):
        fetch_html("https://mp.weixin.qq.com/s/AbC", session=sess, sleep=no_sleep)
    assert len(sess.urls) == 1


def test_long_link_missing_chksm_stops_after_one_request():
    sess = FakeSession([_captcha_redirect(), _captcha_redirect(), _captcha_redirect()])
    with pytest.raises(VerificationRequired) as ei:
        fetch_html("https://mp.weixin.qq.com/s?__biz=AA==&mid=1&idx=1&sn=2", session=sess, sleep=no_sleep)
    assert len(sess.urls) == 1
    assert ei.value.reason == "long_link_missing_chksm"
    assert ei.value.link_kind == "long_no_chksm"
    assert "chksm" in str(ei.value)
    assert len(sess.responses) == 2  # the other profiles were not requested


def test_chksm_link_still_tries_every_profile():
    sess = FakeSession([_captcha_redirect(), _captcha_redirect(), _captcha_redirect()])
    url = "https://mp.weixin.qq.com/s?__biz=AA==&mid=1&idx=1&sn=2&chksm=realvalue&scene=18"
    with pytest.raises(VerificationRequired) as ei:
        fetch_html(url, session=sess, sleep=no_sleep)
    assert len(sess.urls) == 3
    assert ei.value.reason == "all_profiles_challenged"
    assert ei.value.link_kind == "long"
    assert all("chksm=realvalue" in u for u in sess.urls)


def test_poc_sid_cleared_between_profiles(fixture_html):
    page = fixture_html("verify_synthetic.html")
    sess = FakeSession([FakeResp(page)] * 3)
    jar = requests.cookies.RequestsCookieJar()
    jar.set("poc_sid", "abc", domain=".mp.weixin.qq.com", path="/")
    jar.set("rewardsn", "1", domain=".mp.weixin.qq.com", path="/")
    cleared = []
    real_clear = jar.clear

    def spy_clear(domain=None, path=None, name=None):
        cleared.append(name)
        return real_clear(domain, path, name)

    jar.clear = spy_clear
    sess.cookies = jar
    with pytest.raises(VerificationRequired):
        fetch_html("https://mp.weixin.qq.com/s/ExampleShort01", session=sess, sleep=no_sleep)
    assert cleared.count("poc_sid") >= 2
    assert "poc_sid" not in [c.name for c in jar]
    assert "rewardsn" in [c.name for c in jar]


def test_every_request_uses_a_browser_like_ua(fixture_html):
    sess = FakeSession([
        requests.ConnectionError("boom"),
        FakeResp(fixture_html("long_article_synthetic.html")),
    ])
    fetch_html("https://mp.weixin.qq.com/s/AbC", session=sess, retries=1, sleep=no_sleep)
    assert sess.uas
    assert all(ua in USER_AGENTS.values() for ua in sess.uas)
    assert all(not ua.lower().startswith(("curl", "python-requests")) for ua in sess.uas)


def test_session_params_are_not_requested(fixture_html):
    sess = FakeSession([FakeResp(fixture_html("long_article_synthetic.html"))])
    fetch_html(
        "https://mp.weixin.qq.com/s?__biz=MzAw==&mid=1&idx=1&sn=ab&chksm=kk&scene=18"
        "&pass_ticket=SECRET&uin=U&key=K&exportkey=E",
        session=sess, sleep=no_sleep,
    )
    assert "SECRET" not in sess.urls[0]
    assert "pass_ticket" not in sess.urls[0]
    assert "chksm=kk" in sess.urls[0]
    assert "scene=18" in sess.urls[0]
