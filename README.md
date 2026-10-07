# wechat-article-fetcher

把**公开的**微信公众号文章（`mp.weixin.qq.com`）读成干净的 Markdown 或 JSON 的命令行工具 / Python 库。
A small CLI and Python library that turns public WeChat Official Account articles into clean Markdown or JSON.

作者 Yomin Ma · 博客 [yomin.love](https://yomin.love) · GitHub [@mrlong0129](https://github.com/mrlong0129) · MIT License

```bash
wxfetch 'https://mp.weixin.qq.com/s/<文章ID>'
```

## Quick start for agents

零安装、零配置，复制一行就能用（只需要 [uv](https://docs.astral.sh/uv/)）：

```bash
# 1) 直接读一篇公众号文章（不安装）。链接请加引号，避免 shell 把 & 后面的参数吃掉。
#    --refresh 让旧版 uv 重新拉取仓库。更新后如果 MCP 还是旧行为，重启 MCP 客户端。
uvx --refresh --from git+https://github.com/mrlong0129/wechat-article-fetcher wxfetch '<url>'
uvx --refresh --from git+https://github.com/mrlong0129/wechat-article-fetcher wxfetch '<url>' -f json

# 2) Claude Code：一行注册 MCP server（工具：fetch_wechat_article、parse_wechat_html；需要 Python 3.10+）
claude mcp add wechat-article-fetcher -- uvx --refresh --from git+https://github.com/mrlong0129/wechat-article-fetcher wxfetch-mcp
```

**Cursor**：写入 `~/.cursor/mcp.json`（全局）或项目里的 `.cursor/mcp.json`：

```json
{
  "mcpServers": {
    "wechat-article-fetcher": {
      "command": "uvx",
      "args": ["--refresh", "--from", "git+https://github.com/mrlong0129/wechat-article-fetcher", "wxfetch-mcp"]
    }
  }
}
```

**Agent Skill**（不装包也能用，Agent 会照着手册自己读）：

```bash
# Claude Code
mkdir -p ~/.claude/skills/wechat-article-fetcher && curl -fsSL https://raw.githubusercontent.com/mrlong0129/wechat-article-fetcher/main/skill/SKILL.md -o ~/.claude/skills/wechat-article-fetcher/SKILL.md
# Cursor
mkdir -p ~/.cursor/skills/wechat-article-fetcher && curl -fsSL https://raw.githubusercontent.com/mrlong0129/wechat-article-fetcher/main/skill/SKILL.md -o ~/.cursor/skills/wechat-article-fetcher/SKILL.md
```

更新代码之后，已经在跑的 MCP server 仍是启动时的那一版，需要重启 MCP 客户端才会换上新代码。

如果粘贴的是浏览器地址栏里的 `…/mp/wappoc_appmsgcaptcha?poc_token=…&target_url=…`（「环境异常 / 去验证」），wxfetch 会自动改用其中的 `target_url`，不会把 `poc_token` 再发给微信。

给编码 Agent 的完整说明见 [AGENTS.md](AGENTS.md)。要读微信以外的网页，用姊妹项目 [agent-web-fetch](https://github.com/mrlong0129/agent-web-fetch)。

## 功能

- 支持短链接 `https://mp.weixin.qq.com/s/<id>`、长链接 `...?__biz=...&mid=...&idx=...&sn=...`、不带 `https://` 的链接、从网页源码里复制出来带 `&amp;` 的链接
- 一次多篇，或者从文件 / 标准输入批量读（会自动从一段文字里挑出公众号链接）
- 输出 Markdown（默认）或 JSON：标题、公众号名、作者、发布时间（北京时间 ISO 8601）、封面、摘要、正文 Markdown、纯文本、图片列表、用了哪种提取方式
- 被微信的「环境异常 / 去验证」挡住时：如果是客户端（User-Agent）被拦，会换一个再试；如果是长链接缺了 `chksm`，第一次就说明原因，不再把几种 UA 轮一遍。文章被删、违规、链接错误时直接说明原因
- 可选 `--download-images`：把图片存到本地并改写 Markdown 里的图片链接
- 依赖很少：`requests` + `beautifulsoup4` + `lxml`

## 安装

需要 Python 3.8+。

```bash
git clone https://github.com/mrlong0129/wechat-article-fetcher.git
cd wechat-article-fetcher
python3 -m venv .venv && source .venv/bin/activate
pip install -e .            # 开发 / 跑测试：pip install -e '.[dev]'
wxfetch --help
```

## 用法

```bash
# 一篇文章 → Markdown 输出到终端。链接请加引号。
wxfetch 'https://mp.weixin.qq.com/s/<文章ID>'

# 长链接要保留 chksm。不加引号时，shell 会在第一个 & 处把链接截断。
wxfetch 'https://mp.weixin.qq.com/s?__biz=…&mid=…&idx=…&sn=…&chksm=…'

# JSON（单篇输出一个对象，多篇输出数组）
wxfetch 'https://mp.weixin.qq.com/s/<文章ID>' -f json

# 多篇写进一个文件
wxfetch 'URL1' 'URL2' -o articles.md

# 从文件批量读（每行一个链接，# 开头的行忽略；也可以直接丢一段聊天记录进去）
wxfetch -i urls.txt --out-dir out/

# 每篇一个文件，并把图片下载到本地（out/<日期-标题>_images/）
wxfetch -i urls.txt --out-dir out/ --download-images

# Markdown 顶部加 YAML front matter（方便 Obsidian / 静态博客）
wxfetch 'URL' --front-matter -o note.md

# 解析浏览器里「另存为」的 HTML，不联网
wxfetch --from-html saved_page.html -f json

# 查看抓取过程：用了哪个 UA、有没有被要求验证、验证令牌大约是什么时候发出的
wxfetch -v 'URL'
```

| 参数 | 说明 |
| --- | --- |
| `-f markdown\|json` | 输出格式，默认 markdown |
| `-o FILE` / `--out-dir DIR` | 写进一个文件 / 每篇一个文件 |
| `-i FILE` | 从文件读链接，`-` 表示标准输入 |
| `--from-html FILE` | 解析本地 HTML，可重复 |
| `--download-images` / `--images-dir DIR` | 下载图片并改写链接 |
| `--front-matter` | Markdown 加 YAML 头 |
| `--ua ios\|android\|desktop` | 只用指定 UA（可重复，按顺序尝试） |
| `--delay 2.0` | 多篇之间的间隔秒数（带随机抖动） |
| `--retries 2` / `--timeout 20` | 每个 UA 的网络重试次数 / 单次超时 |

退出码：`0` 全部成功，`1` 至少一篇失败（错误信息在 stderr），`2` 用法错误。

### JSON 字段

下面是用测试里的示例页面（占位内容）跑出来的结果：

```jsonc
{
  "url": "https://mp.weixin.qq.com/s/ExampleTextPost01",
  "title": "这是一条用于测试的示例短内容，正文全部是占位文字。",
  "account_nickname": "示例公众号",       // 公众号名
  "author": "示例作者",                   // 文章作者（可能和公众号名不同）
  "publish_time": "2026-10-05T23:59:51+08:00",
  "publish_timestamp": 1791215991,
  "cover_image": "",
  "description": "",
  "content_markdown": "这是一条用于测试的示例短内容……",
  "content_text": "这是一条用于测试的示例短内容……",
  "images": [{"url": "https://mmbiz.qpic.cn/...", "alt": "", "local_path": "note_images/001.png"}],
  "extraction_method": "js_content_noencode",  // 哪种提取方式胜出
  "extraction_candidates": {"js_content_noencode": 129, "og_meta": 129},  // 各方式提取到的字数
  "canonical_url": "https://mp.weixin.qq.com/s/ExampleTextPost01",
  "account_id": "gh_000000000000",
  "account_alias": "ExampleAccount",
  "item_show_type": 10,                   // 0 普通图文，10 纯文字短内容，8 图片消息
  "fetched_with": "ios",                  // 哪个 UA 拿到的页面
  "char_count": 140
  // 正文没有文字、只有图片时，会多一个 warning，例如：
  // "warning": "正文没有提取到文字，共 12 张图片 (no text extracted; 12 image(s))"
}
```

### 作为 Python 库

```python
from wxfetch import fetch_article, extract_article

art = fetch_article("https://mp.weixin.qq.com/s/<文章ID>")
print(art.title, art.account_nickname, art.publish_time)
print(art.content_markdown)

art = extract_article(open("saved.html", encoding="utf-8").read())  # 离线解析
```

## How it works：怎么读一篇公众号文章

> 这一节写成了可以单独阅读的形式，不需要先看上面的用法说明。

### 问题：同一个链接，不同的人看到不同的页面

把一篇公众号文章的链接丢给一个通用的网页抓取服务，经常拿不到正文，只拿到一个写着「环境异常，完成验证后即可继续访问」的页面。可同一个链接在手机微信里点开一切正常。

原因很简单：网站会根据「你是谁、从哪来」决定给你什么。公众号文章本来就是给手机微信的内置浏览器看的；一个从数据中心 IP 发出、自称是某个爬虫的请求，在微信看来就很可疑，于是先丢一个验证页给你。

### 第一步：像手机微信那样去请求

每个 HTTP 请求都带一行 `User-Agent`，告诉网站「我是什么浏览器」。手机微信的 User-Agent 里有一段 `MicroMessenger/8.0.x`，网站就是靠它认出「这是微信」。

所以第一招就是把请求打扮成微信内置浏览器：iPhone 微信的 User-Agent，加上 `Referer: https://mp.weixin.qq.com/` 和 `Accept-Language: zh-CN`。实测公开文章的短链接用这一招基本都能直接拿到完整页面。拿不到就换 Android 微信，再不行换普通桌面 Chrome。

这不是破解。拿到的是任何人用微信打开这个公开链接都能看到的同一个页面，没有绕过登录、付费或者验证码。

### 第二步：先判断拿到的是什么页面

请求回来的不一定是文章，所以先分类：

- **验证页**：被跳转到 `/mp/wappoc_appmsgcaptcha`，或页面里有 `secitptpage`、`poc_token`、「环境异常」「去验证」。换 User-Agent 只对「这个客户端被拦」有用。长链接缺 `chksm` 时，第一次就会说明原因，不再把几种 UA 轮一遍。**不去尝试破解验证码，也不补造 `chksm` 之类的参数。**
- **错误页**：页面里有一个 `weui-msg__title`，写着「该内容已被发布者删除」「此内容因违规无法查看」「参数错误」之类。这种情况换什么方式都没用，直接停下来，把原因告诉用户。
- **网络错误、限流（429）、服务端错误（5xx）**：同一种方式稍等再试，等待时间指数增长并带随机抖动。

批量读的时候每篇之间默认停 2 秒左右，别给对方添麻烦。

### 第三步：正文其实藏在好几个地方

拿到的页面有两三 MB，大部分是 JavaScript。正文通常不止一份：

1. **`<div id="js_content">`**：普通长文的正文就在这里。要用真正的 HTML 解析器去解析，不要用正则「从 js_content 截到 `<script>`」，否则会把一堆脚本当成正文。图片是懒加载的，真实地址在 `data-src`，`src` 里往往只是一个占位图。
2. **页面脚本里的 `content_noencode`**：纯文字的短内容（微信内部叫 `item_show_type = 10`）没有 `js_content`，正文以 JS 字符串的形式放在 `window.cgiDataNew` 里，换行写成 `\x0a`，尖括号写成 `\x3c`。把转义还原，就能得到带链接的正文。
3. **图片列表 `picture_page_info_list`**：图片消息（`item_show_type = 8`）的图片在这里。
4. **`og:title` 等分享元数据**：这是给分享卡片和搜索引擎预览用的 meta 标签。短内容没有标题，微信会把**整段正文**塞进 `og:title`，换行写成字面上的 `\n`。前三种都失败时，它是很好的兜底。

工具会把四种都试一遍，挑提取到字数最多的那份；字数差不多时优先结构最丰富的（`js_content` 有标题、列表、图片，`og:title` 只有纯文本），并记下是哪一种胜出，方便排查。

标题、公众号名、作者、发布时间这些元数据也一样有好几个来源（`var msg_title`、`var nickname`、`var ct` 这类 JS 变量，`cgiDataNew` 对象，页面元素，`og:` 标签），按顺序取第一个非空值。发布时间是 unix 时间戳，转成北京时间 `+08:00`。

### 第四步：把公众号排版变成干净的 Markdown

公众号的正文是层层嵌套的 `<section>` 和 `<span leaf>`，到处是内联样式。转换时只保留阅读需要的东西：标题、段落、列表、引用、加粗、链接、图片、代码块、简单表格。隐藏元素、公众号名片、小程序卡片、空段落都扔掉。

有两个和中文相关的坑：

- **加粗遇到标点**：按 CommonMark 规则，`他说**“重点”**然后` 渲染不出加粗，因为 `**` 紧挨着中文引号。解决办法是把两端的标点挪到外面：`他说“**重点**”然后`。
- **段内换行**：Markdown 里单个换行会被合并成一个空格。公众号里常见「一句一行」的写法，所以段内换行输出成 Markdown 的硬换行（行尾两个空格），段落之间仍然是空行。

### 图片的防盗链

公众号图片放在 `mmbiz.qpic.cn`。实测：不带 Referer，或者 Referer 是 `https://mp.weixin.qq.com/` 时返回原图；Referer 是别的网站时，会返回一张写着「此图片来自微信公众平台，未经允许不可引用」的 2KB 占位图。所以下载图片时带上公众号的 Referer。

### 什么时候会失效

- 长链接如果还带着 `chksm`，可以正常读。被删掉 `chksm` 的长链接（手拼的 `__biz/mid/idx/sn`，或被「去跟踪参数」清掉的链接）一律跳验证页，换 UA 也一样。请用完整原始链接，或在微信里「复制链接」拿 `/s/<id>` 短链接。
- 微信随时可能收紧检测，现在有效的 User-Agent 以后可能就不灵了。
- 这时更重的办法是用真实浏览器（比如 Playwright）打开页面。思路始终是：先用最便宜的方法，不行再上更重的。

## 局限

- **只能读公开文章。** 需要登录、付费、仅粉丝可见、已删除、违规屏蔽的文章都读不到，这个工具也不打算绕过这些限制。
- **缺 `chksm` 的长链接会被要求验证。** 实测（2026-10）同一篇文章：短链接 `/s/<id>`，以及保留了 `chksm` 的长链接，用微信内置浏览器或桌面 Chrome 的 UA 都能直接读到正文。把 `chksm` 删掉之后（手拼的 `__biz/mid/idx/sn`，或被清理跟踪参数的工具处理过），不管用哪种 UA 都会跳到验证页。请粘贴完整的原始链接，或在微信里「复制链接」拿短链接。在 shell 里要给链接加引号，否则 `&` 后面的参数会被截掉。
- **微信随时可能收紧检测。** 频繁请求、数据中心 IP 也更容易被要求验证。
- **不执行 JavaScript。** 完全靠脚本渲染的内容（视频号卡片、投票、部分互动组件）不会出现在结果里；视频只保留占位链接。
- 公众号排版五花八门，转出来的 Markdown 保证可读，不保证和原文排版一模一样。
- 计划中的兜底方案：可选的真实浏览器模式（如 [Playwright](https://playwright.dev/python/)，作为可选依赖），纯 HTTP 被挡住时用无头浏览器打开页面。目前还没有实现，可以先在浏览器里打开文章、另存为 HTML，再用 `--from-html` 解析。

## 负责任地使用

- 文章版权归原作者和公众号所有。这个工具用于**个人阅读、笔记、学习研究**，请不要拿来批量搬运、转载或商用；转载请先获得授权并注明出处。
- 遵守微信公众平台的服务条款和当地法律法规。
- 控制频率：默认每篇间隔约 2 秒，失败会退避重试。请不要调得更激进，也不要大规模并发抓取。
- 被要求验证，说明对方不希望你这样访问。正确的做法是放慢速度、换个时间再试，或者回到微信 / 浏览器里正常阅读，而不是想办法破解验证码。

## 开发

```bash
pip install -e '.[dev]'
pytest              # 离线测试（使用 tests/fixtures 里的页面）
pytest -m live      # 可选：真实请求 mp.weixin.qq.com
```

`tests/fixtures/` 里都是精简过或合成的页面，不包含任何第三方文章正文：

- `text_post_trimmed.html`：按真实「纯文字短内容」页面（`item_show_type=10`）的结构精简而成，保留 `cgiDataNew`、`content_noencode`、`og:` 标签、`window.ct` 等关键结构和几个干扰项；正文、公众号名、ID 都换成了占位内容
- `verify_real.html`：真实的「环境异常」验证页（会话 token 已清除）
- `error_invalid_param_real.html`：真实的「参数错误」页
- `long_article_synthetic.html`、`verify_synthetic.html`、`verify_wechat_ua_synthetic.html`（微信内置浏览器看到的验证页：有 `secitptpage` / `poc_token` / `TCaptcha`，没有「环境异常」这几个字）、`deleted_synthetic.html`、`violation_synthetic.html`、`og_only_synthetic.html`：合成页面

更新记录见 [CHANGELOG.md](CHANGELOG.md)。

## English

**wxfetch** reads *public* WeChat Official Account articles (`mp.weixin.qq.com`) and outputs clean Markdown or JSON: title, account name, author, publish time (ISO 8601, `+08:00`), cover, description, Markdown body, plain text, image list, and which extraction method won.

```bash
pip install -e .
wxfetch 'https://mp.weixin.qq.com/s/<article-id>'               # Markdown to stdout
wxfetch 'https://mp.weixin.qq.com/s?__biz=…&mid=…&idx=…&sn=…&chksm=…'
wxfetch 'URL1' 'URL2' -f json -o articles.json
wxfetch -i urls.txt --out-dir out/ --download-images
wxfetch --from-html saved_page.html                             # offline
```

Quote every URL. An unquoted `&` truncates the link at the first parameter. `uvx --refresh --from git+https://github.com/mrlong0129/wechat-article-fetcher wxfetch '<url>'` forces older uv to re-fetch the repo; restart the MCP client after an update so it drops the process it already started. A pasted `…/mp/wappoc_appmsgcaptcha?poc_token=…&target_url=…` address is unwrapped to `target_url` (the `poc_token` is not sent back).

**How it works.** Requests go out as WeChat's in-app browser (iPhone UA, then Android, then desktop Chrome) with a WeChat `Referer` and `Accept-Language: zh-CN`. Each response is classified first. The "环境异常 / 去验证" captcha page (`wappoc_appmsgcaptcha`, `secitptpage`, `poc_token`) moves on to the next UA only when the challenge depends on the client. A long link with no `chksm` is challenged for every client, so it is reported immediately and no parameter is invented to get past it. Nothing tries to solve the captcha. Deleted, removed or invalid-link pages stop with a clear reason. Network errors, 429 and 5xx are retried with exponential backoff. Content is extracted from up to four sources, and the richest one wins:

- the `#js_content` DOM, parsed with a real HTML parser, with lazy `data-src` images
- the `content_noencode` JS string, for text-only posts
- the picture list, for image posts
- the `og:title` / `og:description` meta tags; for short text posts WeChat stores the entire body in `og:title`, with literal `\n` escapes

The renderer keeps headings, lists, emphasis, links, images, code and tables. It moves punctuation outside `**` so that bold renders in CJK text, and writes line breaks inside a paragraph as Markdown hard breaks. Images are downloaded with `Referer: https://mp.weixin.qq.com/`, because a foreign Referer gets a placeholder image.

**Limitations.**

- Public articles only: no login, paid, fans-only or deleted content, and no attempt to bypass any of those.
- A long `?__biz=` link that still has its `chksm` parameter can be read. The same link with `chksm` removed (hand-built `__biz` / `mid` / `idx` / `sn`, or a link stripped by a tracking-parameter cleaner) is challenged for every client. Use the full original link, or the short `/s/<id>` link from WeChat's "copy link".
- WeChat may tighten detection at any time.
- No JavaScript execution. An optional headless-browser fallback (e.g. Playwright) is a possible future extra.

**Responsible use.** Articles are copyrighted by their authors. Use this tool for personal reading, notes and research. Respect WeChat's Terms of Service, keep request rates low (the default is about 2 s between articles), and don't republish content without permission.

## Related

- **[agent-web-fetch](https://github.com/mrlong0129/agent-web-fetch)**: a general web-reading toolkit for AI agents. It escalates only when blocked, reports why a page couldn't be read, and ships a CLI, an MCP server and an agent skill.

## Author & License

Made by Yomin Ma: [yomin.love](https://yomin.love) · [github.com/mrlong0129](https://github.com/mrlong0129)

[MIT](LICENSE) © 2026 Yomin Ma
