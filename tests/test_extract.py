import base64
import json
import struct
from datetime import datetime, timedelta, timezone

import pytest

from wxfetch import ArticleUnavailable, VerificationRequired, extract_article
from wxfetch.output import slugify, to_json, to_markdown
from wxfetch.pagecheck import classify_page, parse_captcha_url


# --- trimmed real-structure page: short text-only post (item_show_type 10) -------------
TEXT_POST = "text_post_trimmed.html"


def test_text_post_fixture(fixture_html):
    art = extract_article(fixture_html(TEXT_POST), url="https://mp.weixin.qq.com/s/ExampleTextPost01")
    assert art.extraction_method == "js_content_noencode"
    assert art.account_nickname == "示例公众号"  # from cgiDataNew.nick_name
    assert art.author == "示例作者"
    assert art.publish_time == "2026-10-05T23:59:51+08:00"  # window.ct
    assert art.publish_timestamp == 1791215991
    assert art.item_show_type == 10
    assert art.account_id == "gh_000000000000"
    assert art.account_alias == "ExampleAccount"
    assert art.canonical_url == "https://mp.weixin.qq.com/s/ExampleTextPost01"
    # title is derived (WeChat copies the whole body into the title of text posts);
    # decoy `shareCfg = { title: ... }` outside cgiDataNew must not be used
    assert art.title == "这是一条用于测试的示例短内容，正文全部是占位文字。"
    text = art.content_text
    assert text.startswith("这是一条用于测试的示例短内容")
    assert "整段正文就是标题。\n\n第二段" in text  # paragraph kept
    assert "“带引号的词”，还有一个 & 符号" in text  # \x22 / &amp; decoded
    assert text.rstrip().endswith("最后一句用来确认结尾没有被截断。")
    assert "<a" not in text and "\\x0a" not in text and "\\n" not in text
    md = art.content_markdown
    assert ("[示例链接一](https://mp.weixin.qq.com/s?__biz=MzAwMDAwMDAwMA==&mid=1000000001&idx=1"
            "&sn=0123456789abcdef0123456789abcdef&scene=21#wechat_redirect)") in md
    assert "&amp;" not in md
    # single newline inside a paragraph -> Markdown hard break; plain text keeps "\n"
    assert "正文全部是占位文字。  \n它模拟公众号" in md
    assert "正文全部是占位文字。\n它模拟公众号" in text
    assert set(art.extraction_candidates) == {"js_content_noencode", "og_meta"}
    assert art.extraction_candidates["js_content_noencode"] == art.extraction_candidates["og_meta"]


def test_text_post_entity_encoded_variant(fixture_html):
    """Without content_noencode, the entity-encoded text_page_info.content is used."""
    page = fixture_html(TEXT_POST).replace("content_noencode:", "content_noencode_removed:")
    art = extract_article(page)
    assert art.extraction_method == "js_content_noencode"
    assert "[示例链接二](https://mp.weixin.qq.com/s?__biz=MzAwMDAwMDAwMA==&mid=1000000002" in art.content_markdown


def test_og_fallback_when_js_is_missing(fixture_html):
    """Strip every <script>: og:title alone must still give the whole body."""
    import re
    page = re.sub(r"<script\b.*?</script>", "", fixture_html(TEXT_POST), flags=re.S)
    page += "<script>var msg_title = 'x';</script>"  # keep it recognisable as an article
    art = extract_article(page)
    assert art.extraction_method == "og_meta"
    assert art.content_text.endswith("最后一句用来确认结尾没有被截断。")
    assert "整段正文就是标题。\n\n第二段" in art.content_text
    assert "\\n" not in art.content_text
    assert art.author == "示例作者"


def test_og_only_synthetic(fixture_html):
    art = extract_article(fixture_html("og_only_synthetic.html"))
    assert art.extraction_method == "og_meta"
    assert art.title == "第一行短内容，没有标题的文字消息。"
    assert art.content_text == "第一行短内容，没有标题的文字消息。\n第二行继续。\n\n第二段，含转义 & 符号。"
    assert art.publish_time == "2026-10-05T23:59:51+08:00"


# --- synthetic normal long article -----------------------------------------------------
@pytest.fixture
def long_art(fixture_html):
    return extract_article(fixture_html("long_article_synthetic.html"),
                           url="https://mp.weixin.qq.com/s/SyntheticLongArticle01")


def test_long_metadata(long_art):
    a = long_art
    assert a.extraction_method == "js_content"
    assert a.title == "合成长文：如何测试公众号抓取"
    assert a.account_nickname == "合成测试号"
    assert a.author == "测试作者"
    assert a.publish_time == "2025-09-11T17:39:59+08:00"
    assert a.cover_image == "https://mmbiz.qpic.cn/mmbiz_jpg/COVER/0?wx_fmt=jpeg"  # http -> https
    assert a.description == "一篇用于测试的合成长文 & 描述"
    assert a.account_id == "gh_synthetic01"
    assert a.canonical_url == "https://mp.weixin.qq.com/s/SyntheticLongArticle01"


def test_long_markdown_structure(long_art):
    md = long_art.content_markdown
    assert "## 一、背景" in md
    assert "### 1.1 列表" in md
    assert "这是第一段，包含**加粗文字**和一个[外部链接](https://example.com/doc?a=1&b=2)。" in md
    # CJK-safe bold: punctuation moved outside the markers
    assert "他说“**这是引号里的重点**”然后继续。" in md
    assert "- 第一项\n- **第二项**：说明  \n  第二项的补充行\n\n  - 嵌套子项" in md
    assert "1. 步骤一\n2. 步骤二" in md
    assert "> 引用的一句话。" in md
    assert '```python\ndef hello():\n    print("hi")\n```' in md
    assert "| 模型 | 分数 |" in md and "| 示例模型 | 88.0 |" in md
    assert "*斜体结尾*" in md
    assert "**欢迎关注**「**示例号**」" in md  # adjacent bold runs merged, no '****'
    assert "****" not in md
    assert "同一段里的第一行  \n同一段里的第二行" in md  # <br> -> hard break


def test_long_drops_noise(long_art):
    md = long_art.content_markdown
    assert "隐藏的段落" not in md  # display:none
    assert "不应出现的签名" not in md  # mp-common-profile widget
    assert "decoy" not in md
    assert "\n\n\n" not in md
    for line in md.split("\n"):
        if line.startswith((" ", "    ")):  # list continuation / code
            continue
        assert line == line.lstrip()
        assert line == line.rstrip() or line.endswith(("  ",)) and not line.endswith("   ")
    assert "data:image" not in md


def test_long_lazy_images(long_art):
    urls = [i.url for i in long_art.images]
    assert urls == [
        "https://mmbiz.qpic.cn/mmbiz_png/AAAA/640?wx_fmt=png&from=appmsg",  # data-src beats data: src
        "https://mmbiz.qpic.cn/mmbiz_jpg/BBBB/640?wx_fmt=jpeg",  # protocol-relative fixed
    ]
    assert "![示意图](https://mmbiz.qpic.cn/mmbiz_png/AAAA/640?wx_fmt=png&from=appmsg)" in long_art.content_markdown


def test_long_plain_text(long_art):
    t = long_art.content_text
    assert "**" not in t and "](" not in t and "#" not in t
    assert "这是第一段，包含加粗文字和一个外部链接。" in t
    assert "同一段里的第一行\n同一段里的第二行" in t
    assert not any(line.endswith(" ") for line in t.split("\n"))


# --- error pages -----------------------------------------------------------------------
@pytest.mark.parametrize("name", ["verify_real.html", "verify_synthetic.html", "verify_wechat_ua_synthetic.html"])
def test_verification_pages(fixture_html, name):
    with pytest.raises(VerificationRequired) as ei:
        extract_article(fixture_html(name))
    assert ei.value.reason == "verification_page"


def test_wechat_ua_captcha_has_no_environment_text(fixture_html):
    page = fixture_html("verify_wechat_ua_synthetic.html")
    assert "环境异常" not in page
    assert "secitptpage" in page and "poc_token" in page and "TCaptcha" in page
    assert classify_page(page)[0] == "verify"


def test_tcaptcha_counts_only_with_poc_token():
    assert classify_page("<html><script src='https://captcha.gtimg.com/TCaptcha.js'></script></html>")[0] != "verify"
    assert classify_page("<html><script src='https://captcha.gtimg.com/TCaptcha.js'></script>poc_token='x'</html>")[0] == "verify"


def test_article_text_mentioning_poc_token_is_not_captcha():
    page = '<div id="js_content"><p>正文里出现 poc_token 这个词，但仍然是文章。</p></div>'
    assert classify_page(page)[0] == "article"


def test_parse_captcha_url_reads_issue_time():
    ts = 1791215991  # 2026-10-05 23:59:51 +08:00, inside the accepted window
    raw = bytes([0x01]) + struct.pack("<I", ts) + b"\x00" * 8
    token = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    info = parse_captcha_url(
        "https://mp.weixin.qq.com/mp/wappoc_appmsgcaptcha"
        f"?poc_token={token}&target_url=https%3A%2F%2Fmp.weixin.qq.com%2Fs%2FAbC"
    )
    cst = timezone(timedelta(hours=8))
    assert info is not None
    assert info.poc_token == token
    assert info.target_url == "https://mp.weixin.qq.com/s/AbC"
    assert info.issued_at == datetime.fromtimestamp(ts, cst)

    old = base64.urlsafe_b64encode(bytes([0x01]) + struct.pack("<I", 100)).decode().rstrip("=")
    stale = parse_captcha_url(f"https://mp.weixin.qq.com/mp/wappoc_appmsgcaptcha?poc_token={old}")
    assert stale is not None and stale.issued_at is None
    assert parse_captcha_url("https://mp.weixin.qq.com/s/AbC") is None


@pytest.mark.parametrize("name,reason", [
    ("deleted_synthetic.html", "deleted"),
    ("violation_synthetic.html", "violation"),
    ("error_invalid_param_real.html", "invalid_link"),
])
def test_unavailable_pages(fixture_html, name, reason):
    with pytest.raises(ArticleUnavailable) as ei:
        extract_article(fixture_html(name))
    assert ei.value.reason == reason


# --- output ----------------------------------------------------------------------------
def test_markdown_and_json_output(long_art):
    md = to_markdown(long_art, front_matter=True)
    assert md.startswith("---\ntitle: \"合成长文：如何测试公众号抓取\"")
    assert "# 合成长文：如何测试公众号抓取" in md
    assert "> 公众号：合成测试号 ｜ 作者：测试作者 ｜ 发布时间：2025-09-11 17:39:59+08:00" in md
    data = json.loads(to_json([long_art], single=True))
    for key in ("url", "title", "account_nickname", "author", "publish_time", "cover_image",
                "description", "content_markdown", "content_text", "images", "extraction_method"):
        assert key in data
    assert data["char_count"] == len(long_art.content_text)
    assert slugify(long_art) == "20250911-合成长文：如何测试公众号抓取"
