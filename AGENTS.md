# AGENTS.md — wechat-article-fetcher

Instructions for coding agents (Claude Code, Cursor, Codex, etc.) that want to **use** this tool or **work on** this repo.

## Use it in one step (no install, no config)

```bash
uvx --refresh --from git+https://github.com/mrlong0129/wechat-article-fetcher wxfetch '<url>'           # Markdown to stdout
uvx --refresh --from git+https://github.com/mrlong0129/wechat-article-fetcher wxfetch '<url>' -f json   # JSON
```

`--refresh` forces older uv to re-fetch the git repo. Quote the URL: an unquoted `&` truncates it. After updating, restart the MCP client; a long-running server keeps the code it was started with.

Only [uv](https://docs.astral.sh/uv/) is needed (`curl -LsSf https://astral.sh/uv/install.sh | sh`). No API keys or environment variables; defaults work as-is.

Register the MCP server (Python 3.10+; the MCP SDK installs automatically):

```bash
claude mcp add wechat-article-fetcher -- uvx --refresh --from git+https://github.com/mrlong0129/wechat-article-fetcher wxfetch-mcp
```

Cursor (`~/.cursor/mcp.json` or `.cursor/mcp.json`):

```json
{"mcpServers": {"wechat-article-fetcher": {"command": "uvx", "args": ["--refresh", "--from", "git+https://github.com/mrlong0129/wechat-article-fetcher", "wxfetch-mcp"]}}}
```

MCP tools: `fetch_wechat_article(url, format="markdown"|"text"|"both", max_chars=40000)` and `parse_wechat_html(html, url=None, format, max_chars)`.

Install the skill (works even without the package):

```bash
mkdir -p ~/.claude/skills/wechat-article-fetcher && curl -fsSL https://raw.githubusercontent.com/mrlong0129/wechat-article-fetcher/main/skill/SKILL.md -o ~/.claude/skills/wechat-article-fetcher/SKILL.md
```

## How to read results

- CLI exit codes: `0` all ok, `1` at least one article failed (reason on stderr), `2` usage error.
- MCP: `ok: true` → `title`, `account_nickname`, `author`, `publish_time`, `content_markdown`, `images`, `extraction_method`. An article with images but no text also has `warning` and the image count. `ok: false` → `error` is `verification_required` (with `reason` and `link_kind`), `article_unavailable` (with `reason`), `invalid_url` or `fetch_error`.
- On `verification_required`, read `reason` and do not retry in a loop or try to solve the captcha:
  - `long_link_missing_chksm`: the long `?__biz=` link has no `chksm`. WeChat challenges that URL form for every client. Ask for the full original link (keep `&chksm=`) or the `/s/<id>` short link from WeChat's "copy link". Do not retry and do not invent a `chksm`.
  - `all_profiles_challenged`: a short link, a temporary link, or a long link that still has `chksm` was challenged on every profile. That is a network or rate-limit signal. Suggest trying later, another network, or saving the page as HTML and using `wxfetch --from-html page.html` / `parse_wechat_html`.
- A pasted captcha-page URL (`/mp/wappoc_appmsgcaptcha?poc_token=…&target_url=…`) is unwrapped to `target_url`. `poc_token` is never sent back. Other non-article paths are rejected.
- Long links that keep a real `chksm` work. Login-session parameters (`key`, `pass_ticket`, `uin`, `exportkey`) are stripped.
- For general (non-WeChat) web pages use the sibling project [agent-web-fetch](https://github.com/mrlong0129/agent-web-fetch).

## Work on this repo

```bash
uv venv && . .venv/bin/activate && uv pip install -e ".[dev]"
pytest              # offline, fast; must pass before committing
pytest -m live      # optional live smoke tests
```

- Code: `src/wxfetch/` — `fetcher.py` (UA fallback, retries), `pagecheck.py` (verification / deleted detection), `extractor.py` (candidates), `render.py` (HTML → Markdown), `cli.py`, `mcp_server.py`.
- Fixtures must not contain third-party article text or real account IDs/tokens; use placeholders like the existing `text_post_trimmed.html`.
- Never add captcha solving or logged-in session reuse.
