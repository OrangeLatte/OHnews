"""按需单页正文抓取（方案 C）：收件箱摘要源入 case 时补全文。

合规边界（工程守则）：仅用户显式触发（attach_document 入案）、单次请求、
15s 超时、标识 UA、不绕过任何反爬（无 cookie/无重试轰炸）；失败返回空串
由调用方保持原 body（诚实降级，不阻塞入案）。
"""

from __future__ import annotations

import html as _html
import re as _re
import urllib.request

from oh_contracts.text import strip_html

_UA = "OHNews-CaseFetcher/1.0 (+research tool; respects robots)"

_BLOCK_TAGS = ("script", "style", "noscript", "nav", "footer", "header", "aside", "form")

_NOISE_PHRASES = (
    "skip to main",
    "top stories",
    "subscribe",
    "sign in",
    "newsletter",
    "advertisement",
    "read more",
    "related topics",
    "share this",
    "all rights reserved",
    "privacy policy",
    "cookie",
    "save log in",
    "get email alerts",
    "back to top",
    "follow us",
)


def _is_noise(seg: str) -> bool:
    """噪音短语只对短片段生效：正文长句偶含 read more 等词不应误杀。"""
    if len(seg) > 160:
        return False
    low = seg.lower()
    return any(n in low for n in _NOISE_PHRASES)


def clean_article_text(raw: str) -> str:
    """公共正文清洗（使用时清洗）：剔块级标签/导航噪音短语，旧数据受益。"""
    return _clean(raw)


def _clean(raw: str) -> str:
    """块级噪音标签剔除 + 实体解码 + 行/句级噪音短语过滤。"""
    for tag in _BLOCK_TAGS:
        raw = _re.sub(
            rf"<{tag}[^>]*>.*?</{tag}>",
            " ",
            raw,
            flags=_re.DOTALL | _re.IGNORECASE,
        )
    text = _html.unescape(strip_html(raw)).strip()
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not _is_noise(ln)]
    sents = _re.split(r"(?<=[\u4e00-\u9fff。！？]|[.!?])\s+", " ".join(lines))
    kept = [x.strip() for x in sents if x.strip() and not _is_noise(x)]
    text = " ".join(kept)
    text = _re.sub(r"[ \t\u00a0]{2,}", " ", text)
    return _re.sub(r"\n{3,}", "\n\n", text)


def fetch_page_text(url: str, *, timeout: float = 15.0) -> str:
    """抓取单页并抽取纯文本正文；任何失败返回空串。"""
    if not url.lower().startswith(("http://", "https://")):
        return ""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            if resp.status != 200:
                return ""
            charset = resp.headers.get_content_charset() or "utf-8"
            raw = resp.read(1_500_000).decode(charset, "ignore")
    except Exception:  # noqa: BLE001 —— 网络失败诚实降级
        return ""
    text = _clean(raw)
    return text if len(text) >= 80 else ""
