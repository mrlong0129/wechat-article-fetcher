# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [0.1.1] - 2026-10-07

### Fixed

- Captcha-page URLs pasted as input (`/mp/wappoc_appmsgcaptcha?poc_token=…&target_url=…`) are unwrapped to their `target_url`. The `poc_token` is never sent back.
- Long links missing `chksm` are reported immediately (one request) with reason `long_link_missing_chksm`, instead of cycling User-Agents.
- A short link, a temporary link, or a long link that still has `chksm`, when challenged on every profile, is reported as `all_profiles_challenged` (likely network or rate limit).
- Login-session parameters (`key`, `pass_ticket`, `uin`, `exportkey`, and similar) are stripped. A real `chksm` and `scene` are kept. Nothing is added to the URL.
- Non-article `mp.weixin.qq.com` paths are rejected with a clear error. A long link that lost `mid` / `sn` (often an unquoted `&` in the shell) says to quote the URL.
- Docs: long links that keep `chksm` work; examples quote URLs; `uvx --refresh`; restart the MCP client after updating; pasted captcha-page URLs are explained.

### Added

- When an article has images but no extracted text, the CLI warns and the JSON / MCP result includes `warning` with the image count.

## [0.1.0] - 2026-10-06

First public release.

### Added

- `wxfetch` command-line tool and `wxfetch` Python package (`fetch_article`, `extract_article`).
- Input: short `/s/<id>` links, long `?__biz=` links, scheme-less and `&amp;`-escaped links, URL files or stdin (`-i`), and saved HTML files (`--from-html`).
- Output: Markdown (default, optional YAML front matter) or JSON. Fields: url, title, account nickname, author, publish time (ISO 8601 `+08:00`), cover image, description, `content_markdown`, `content_text`, images and `extraction_method`. Results go to stdout, to one file (`-o`), or to one file per article (`--out-dir`).
- Fetching: falls back from the iPhone WeChat UA to the Android WeChat UA to desktop Chrome, sends WeChat `Referer` and `Accept-Language` headers, retries with exponential backoff and jitter, and waits a polite delay between articles.
- Page classification: detects the verification page (`环境异常` / `去验证` / `secitptpage` / `wappoc_appmsgcaptcha`) and deleted, violation, migrated, expired and invalid-link pages, each with a clear reason.
- Extraction from four candidates, where the richest wins and the method is recorded:
  - `js_content` (an HTML parser over `#js_content`, with lazy `data-src` images)
  - `js_content_noencode` (text-only posts)
  - `picture_page` (image posts)
  - `og_meta` (`og:title` / `og:description` fallback, with `\n` / `\x` escapes decoded)
- A WeChat-aware HTML to Markdown renderer:
  - keeps headings, lists (including nested ones), quotes, emphasis, links, images, code blocks and tables
  - drops hidden elements and widgets
  - makes bold CJK-safe and merges adjacent bold runs
  - writes line breaks inside a paragraph as hard breaks
- `--download-images` saves images with a WeChat Referer and rewrites Markdown links to the local files.
- Offline pytest suite built on trimmed and synthetic fixtures, plus optional live tests (`pytest -m live`).
- Agent-friendly setup: zero-install `uvx --from git+https://github.com/mrlong0129/wechat-article-fetcher wxfetch <url>`, `AGENTS.md`, and an agent skill at `skill/SKILL.md`.
- `wxfetch-mcp`: a small MCP server (stdio) with the tools `fetch_wechat_article` and `parse_wechat_html`. The MCP SDK is installed automatically on Python 3.10+.

[0.1.1]: https://github.com/mrlong0129/wechat-article-fetcher/releases/tag/v0.1.1
[0.1.0]: https://github.com/mrlong0129/wechat-article-fetcher/releases/tag/v0.1.0
