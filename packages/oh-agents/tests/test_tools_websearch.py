"""tools_websearch 测试：monkeypatch fetch，不打真实网络。"""

from __future__ import annotations

from typing import Any

from oh_agents.tools_websearch import (
    _parse_ddg,
    _strip_pii,
    tavily_ready,
    web_extract,
    web_search,
)


class _Resp:
    def __init__(self, payload: Any, ok: bool = True) -> None:
        self._payload = payload
        self.ok = ok

    def json(self) -> Any:
        return self._payload

    @property
    def text(self) -> str:
        return self._payload if isinstance(self._payload, str) else ""


def test_strip_pii_removes_email_and_phone() -> None:
    q = "contact john@example.com or +1 415 555 1234 about fed"
    out = _strip_pii(q)
    assert "john@" not in out and "415" not in out
    assert "fed" in out


def test_web_search_tavily_primary() -> None:
    calls: list[dict[str, Any]] = []

    def fetch(path: str, payload: dict[str, Any] | None) -> _Resp:
        calls.append({"path": path, "payload": payload})
        return _Resp({"results": [{"title": "T", "url": "https://x", "content": "body"}]})

    out = web_search("fed decision", api_key="tvly-1", fetch=fetch)
    assert calls[0]["path"] == "search"
    assert out == [{"title": "T", "url": "https://x", "snippet": "body"}]


def test_web_search_falls_back_to_ddg_without_key() -> None:
    html = (
        '<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fnews.x%2Fa">Reuters</a>'
    )
    seen: list[dict[str, Any]] = []

    def fetch(path: str, payload: dict[str, Any] | None) -> _Resp:
        seen.append(payload or {})
        return _Resp(html)

    out = web_search("usdc", api_key=None, fetch=fetch)
    assert len(out) == 1
    assert out[0]["title"] == "Reuters"
    assert out[0]["url"].startswith("https://")
    assert seen[0]["query"] == "usdc"


def test_web_search_ddg_parse_limit_and_empty() -> None:
    rows = "".join(f'<a class="result__a" href="https://x/{i}">t{i}</a>' for i in range(8))
    assert len(_parse_ddg(rows, limit=5)) == 5
    assert _parse_ddg("", limit=5) == []
    assert web_search("   ", api_key="k") == []


def test_web_extract_tavily_only() -> None:
    def fetch(path: str, payload: dict[str, Any] | None) -> _Resp:
        assert path == "extract"
        return _Resp({"results": [{"url": "https://a", "raw_content": "text"}]})

    out = web_extract(["https://a", "https://b"], api_key="k", fetch=fetch)
    assert out == {"https://a": "text", "https://b": ""}


def test_web_extract_no_key_or_fail_empty() -> None:
    assert web_extract(["https://a"], api_key=None) == {"https://a": ""}

    def fail(path: str, payload: dict[str, Any] | None) -> _Resp:
        return _Resp({}, ok=False)

    assert web_extract(["https://a"], api_key="k", fetch=fail) == {"https://a": ""}


def test_tavily_ready() -> None:
    assert tavily_ready("tvly-1") is True
    assert tavily_ready("  ") is False
    assert tavily_ready(None) is False
