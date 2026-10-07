import json
from pathlib import Path

from wxfetch import extract_article
from wxfetch.cli import main
from wxfetch.images import download_images

FIX = Path(__file__).parent / "fixtures"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


class ImgResp:
    def __init__(self, content=PNG, ctype="image/png", status=200):
        self.content = content
        self.headers = {"Content-Type": ctype}
        self.status_code = status


class ImgSession:
    def __init__(self):
        self.calls = []

    def get(self, url, headers=None, timeout=None):
        self.calls.append((url, headers))
        return ImgResp(ctype="image/jpeg" if "jpeg" in url else "image/png")


def test_download_images_rewrites_links(tmp_path, fixture_html):
    art = extract_article(fixture_html("long_article_synthetic.html"))
    sess = ImgSession()
    n = download_images(art, tmp_path / "a_images", link_base=tmp_path, session=sess, sleep=lambda s: None)
    assert n == 3  # 2 body images + cover
    assert (tmp_path / "a_images" / "001.png").exists()
    assert (tmp_path / "a_images" / "002.jpg").exists()
    assert (tmp_path / "a_images" / "cover.jpg").exists()
    assert "![示意图](a_images/001.png)" in art.content_markdown
    assert "![](a_images/002.jpg)" in art.content_markdown
    assert "mmbiz.qpic.cn/mmbiz_png/AAAA" not in art.content_markdown
    assert art.images[0].local_path == "a_images/001.png"
    # WeChat's image CDN must see a WeChat Referer (a foreign one gets a placeholder image)
    assert all(h["Referer"] == "https://mp.weixin.qq.com/" for _, h in sess.calls)


def test_cli_from_html_json(capsys):
    rc = main(["--from-html", str(FIX / "text_post_trimmed.html"), "-f", "json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["extraction_method"] == "js_content_noencode"
    assert data["account_nickname"] == "示例公众号"


def test_cli_markdown_out_dir(tmp_path):
    rc = main(["--from-html", str(FIX / "long_article_synthetic.html"), "--out-dir", str(tmp_path)])
    assert rc == 0
    files = list(tmp_path.glob("*.md"))
    assert len(files) == 1
    assert files[0].read_text(encoding="utf-8").startswith("# 合成长文：如何测试公众号抓取")


def test_cli_reports_failures(capsys):
    rc = main(["--from-html", str(FIX / "verify_real.html")])
    assert rc == 1
    assert "verification" in capsys.readouterr().err


def test_cli_no_input(capsys):
    assert main([]) == 2


def test_cli_prints_missing_chksm_reason(monkeypatch, capsys):
    from datetime import datetime, timedelta, timezone

    from wxfetch.errors import VerificationRequired
    from wxfetch.pagecheck import CaptchaInfo

    issued = datetime(2026, 10, 7, 23, 19, 38, tzinfo=timezone(timedelta(hours=8)))

    def boom(url, **kwargs):
        raise VerificationRequired(
            "长链接缺少 chksm 参数，微信对这类链接一律要求验证。",
            reason="long_link_missing_chksm",
            link_kind="long_no_chksm",
            captcha=CaptchaInfo(poc_token="x", issued_at=issued),
            attempts=["ios#1: verify (redirect)"],
        )

    monkeypatch.setattr("wxfetch.cli.fetch_html", boom)
    rc = main(["-v", "https://mp.weixin.qq.com/s?__biz=AA==&mid=1&idx=1&sn=2"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "verification required (long_link_missing_chksm)" in err
    assert "poc_token issued 2026-10-07 23:19:38 UTC+8" in err
    assert "稍后再试" not in err


def test_image_only_article_warns(tmp_path, capsys, caplog):
    page = """<!DOCTYPE html><html><head><meta charset="utf-8"></head><body>
    <div id="js_content"><p><img data-src="https://mmbiz.qpic.cn/mmbiz_png/AAAA/640?wx_fmt=png" alt=""/></p>
    <img data-src="https://mmbiz.qpic.cn/mmbiz_jpg/BBBB/640?wx_fmt=jpeg" /></div>
    </body></html>"""
    path = tmp_path / "images.html"
    path.write_text(page, encoding="utf-8")
    with caplog.at_level("WARNING", logger="wxfetch"):
        rc = main(["--from-html", str(path), "-f", "json"])
    captured = capsys.readouterr()
    assert rc == 0
    data = json.loads(captured.out)
    assert data["char_count"] == 0
    assert not data["content_text"].strip()
    assert len(data["images"]) == 2
    assert data["warning"] == "正文没有提取到文字，共 2 张图片 (no text extracted; 2 image(s))"
    assert "共 2 张图片" in caplog.text
