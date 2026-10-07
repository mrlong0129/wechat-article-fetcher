"""Exception types. Every error carries a short, human-readable message."""


class WxFetchError(Exception):
    """Base class for all wxfetch errors."""


class InvalidURL(WxFetchError):
    """The input is not a recognisable mp.weixin.qq.com article URL."""


class FetchError(WxFetchError):
    """Network / HTTP failure after all retries and fallbacks."""


class VerificationRequired(WxFetchError):
    """WeChat answered with its '环境异常 / 去验证' captcha page.

    ``reason`` is a machine-friendly code:

    - ``long_link_missing_chksm`` — a ``?__biz=`` link without ``chksm``. WeChat
      challenges that URL form for every client, so the tool stops after one request.
    - ``all_profiles_challenged`` — a short link, a temporary link, or a long link
      that still has ``chksm`` was challenged on every User-Agent profile.
    - ``verification_page`` — the HTML itself is the captcha page (for example a
      file passed to ``--from-html``).

    ``str(exc)`` stays the human-readable message.
    """

    def __init__(self, message, reason="all_profiles_challenged", link_kind=None,
                 captcha=None, attempts=None):
        self.reason = reason
        self.link_kind = link_kind
        self.captcha = captcha
        self.attempts = list(attempts or [])
        super().__init__(message)


class ArticleUnavailable(WxFetchError):
    """WeChat says the article is gone (deleted, removed for violation, bad link, ...).

    ``reason`` is a short machine-friendly code, ``message`` is WeChat's own wording.
    """

    def __init__(self, reason: str, message: str):
        self.reason = reason
        self.message = message
        super().__init__(f"{reason}: {message}")


class ExtractionError(WxFetchError):
    """The page looked like an article but no content could be extracted."""
