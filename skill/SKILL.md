---
name: wechat-article-fetcher
description: Read public WeChat Official Account articles (微信公众号文章, mp.weixin.qq.com links) as clean Markdown or JSON with title, account name, author and publish time. Use whenever the user shares an mp.weixin.qq.com link or asks to read, summarise or save a 公众号 article. Handles WeChat's "环境异常" verification page by switching to the WeChat in-app client, and reports deleted / violation / verification cases instead of bypassing them.
---

# Reading WeChat Official Account articles

## 1. Use the tool if you can (zero install, zero config)

```bash
uvx --from git+https://github.com/mrlong0129/wechat-article-fetcher wxfetch <url>            # Markdown
uvx --from git+https://github.com/mrlong0129/wechat-article-fetcher wxfetch <url> -f json    # JSON
```

Or, if installed: `wxfetch <url>`. With the MCP server registered, call `fetch_wechat_article(url)`; for a page saved as HTML, `parse_wechat_html(html)`.

Exit code `1` means the article could not be read; stderr says why (`需要验证 verification required`, `文章不可用 article unavailable (deleted / violation / invalid_link …)`). Tell the user that reason; do not retry in a loop.

## 2. The same method by hand (no tool available)

1. **Use the short link** `https://mp.weixin.qq.com/s/<id>`. Long `?__biz=...&mid=...` links are almost always challenged outside WeChat.
2. **Request it as WeChat's in-app browser would** (the pages are built for it):
   ```
   User-Agent: Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.47(0x18002f2f) NetType/WIFI Language/zh_CN
   Accept-Language: zh-CN,zh;q=0.9
   Referer: https://mp.weixin.qq.com/
   ```
   A different network egress (your own machine instead of a cloud fetch service) often helps.
3. **Check what you got.** If the page says `环境异常` / `完成验证后即可继续访问` / `去验证`, it is the verification page: try the Android WeChat UA, then desktop Chrome, once each with a pause of 1–2 s. Never solve the captcha. `该内容已被发布者删除`, `此内容因违规无法查看`, `参数错误` mean the article is gone or the link is bad: stop and report.
4. **Extract, richest source first:**
   - Long articles: the `#js_content` element (it is hidden with CSS until JS runs; read it anyway). Images use `data-src`, not `src`.
   - Short text posts (`item_show_type` 10): `#js_content` is empty; the full text is the JS string `content_noencode` inside `window.cgiDataNew` (decode `\x0a`, `\x22`, `&amp;`), and usually also in `og:title`.
   - Image posts (`item_show_type` 8): the images are in `picture_page_info_list`.
   - Metadata: account name `nick_name`, author `author`, publish time `ori_create_time` / `ct` (Unix seconds; show as China time, +08:00), account id `user_name` (`gh_…`).
5. **Images** on `mmbiz.qpic.cn` load with no Referer or with `https://mp.weixin.qq.com/`; other Referers get a placeholder.

## When you can't read it

Say so plainly and offer a way forward, e.g. "WeChat returned its 环境异常 verification page, so I couldn't read the article. If you open it in WeChat and paste the text (or save the page as HTML and send it), I'll work from that."

## Responsible use

Public articles only (no login, paid or fans-only content). Keep at least ~2 s between articles, don't bulk-mirror accounts, respect authors' copyright (summarise and link; don't republish whole articles).
