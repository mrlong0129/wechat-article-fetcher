"""Exception types. Every error carries a short, human-readable message."""


class WxFetchError(Exception):
    """Base class for all wxfetch errors."""


class InvalidURL(WxFetchError):
    """The input is not a recognisable mp.weixin.qq.com article URL."""


class FetchError(WxFetchError):
    """Network / HTTP failure after all retries and fallbacks."""


class VerificationRequired(WxFetchError):
    """WeChat answered with its '环境异常 / 去验证' captcha page for every UA we tried."""


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
