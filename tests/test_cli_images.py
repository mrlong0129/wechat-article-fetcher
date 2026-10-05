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
