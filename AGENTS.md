# AGENTS.md — wechat-article-fetcher

Instructions for coding agents (Claude Code, Cursor, Codex, etc.) that want to **use** this tool or **work on** this repo.

## Use it in one step (no install, no config)

```bash
uvx --from git+https://github.com/mrlong0129/wechat-article-fetcher wxfetch <url>           # Markdown to stdout
uvx --from git+https://github.com/mrlong0129/wechat-article-fetcher wxfetch <url> -f json   # JSON
```

Only [uv](https://docs.astral.sh/uv/) is needed (`curl -LsSf https://astral.sh/uv/install.sh | sh`). No API keys or environment variables; defaults work as-is.

Register the MCP server (Python 3.10+; the MCP SDK installs automatically):

```bash
claude mcp add wechat-article-fetcher -- uvx --from git+https://github.com/mrlong0129/wechat-article-fetcher wxfetch-mcp
```

Cursor (`~/.cursor/mcp.json` or `.cursor/mcp.json`):

```json
{"mcpServers": {"wechat-article-fetcher": {"command": "uvx", "args": ["--from", "git+https://github.com/mrlong0129/wechat-article-fetcher", "wxfetch-mcp"]}}}
```

MCP tools: `fetch_wechat_article(url, format="markdown"|"text"|"both", max_chars=40000)` and `parse_wechat_html(html, url=None, format, max_chars)`.

Install the skill (works even without the package):

```bash
mkdir -p ~/.claude/skills/wechat-article-fetcher && curl -fsSL https://raw.githubusercontent.com/mrlong0129/wechat-article-fetcher/main/skill/SKILL.md -o ~/.claude/skills/wechat-article-fetcher/SKILL.md
```

## How to read results

- CLI exit codes: `0` all ok, `1` at least one article failed (reason on stderr), `2` usage error.
- MCP: `ok: true` → `title`, `account_nickname`, `author`, `publish_time`, `content_markdown`, `images`, `extraction_method`. `ok: false` → `error` is `verification_required`, `article_unavailable` (with `reason`), `invalid_url` or `fetch_error`.
- On `verification_required`, do not retry in a loop or try to solve the captcha: tell the user, suggest opening the article in WeChat, or saving the page as HTML and using `wxfetch --from-html page.html` / `parse_wechat_html`.
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
