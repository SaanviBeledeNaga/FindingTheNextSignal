import sys
from types import SimpleNamespace

import pytest

from pharma_scope.webtools import WebTools
from pharma_scope.config import doctor


def test_duckduckgo_without_search_keys(monkeypatch):
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    calls = []
    class FakeDDGS:
        def __init__(self, **kwargs):
            calls.append(kwargs)
        def text(self, query, **kwargs):
            calls.append(kwargs)
            return [{"href": "https://issuer.example/report", "title": "Annual report", "body": "Search lead"}]
    monkeypatch.setitem(sys.modules, "ddgs", SimpleNamespace(DDGS=FakeDDGS))
    result = WebTools("duckduckgo").search("annual report", count=3)
    assert result == [{"url": "https://issuer.example/report", "title": "Annual report", "snippet": "Search lead"}]
    assert calls[1]["backend"] == "duckduckgo"


def test_duckduckgo_rate_limit_is_not_silently_hidden(monkeypatch):
    class FailingDDGS:
        def __init__(self, **kwargs):
            pass
        def text(self, *args, **kwargs):
            raise RuntimeError("Rate limited")
    monkeypatch.setitem(sys.modules, "ddgs", SimpleNamespace(DDGS=FailingDDGS))
    with pytest.raises(ValueError, match="may be rate-limited"):
        WebTools("duckduckgo").search("annual report")


def test_doctor_does_not_require_search_key_for_duckduckgo(monkeypatch):
    monkeypatch.setenv("PHARMA_PROVIDER", "gemini")
    monkeypatch.setenv("PHARMA_MODEL", "test-model")
    monkeypatch.setenv("GEMINI_API_KEY", "unit-test-key")
    monkeypatch.setenv("PHARMA_SEARCH_PROVIDER", "duckduckgo")
    monkeypatch.setattr("pharma_scope.config.importlib.util.find_spec", lambda name: object())
    result = doctor()
    assert result["search_key_required"] is False
    assert result["search_key_configured"] is None
    assert result["ready_for_live_research"] is True


def test_public_bing_fallback_when_duckduckgo_unavailable(monkeypatch):
    backends = []
    class FallbackDDGS:
        def __init__(self, **kwargs):
            pass
        def text(self, query, **kwargs):
            backends.append(kwargs["backend"])
            if kwargs["backend"] == "duckduckgo":
                raise RuntimeError("Unavailable")
            return [{"href": "https://issuer.example/report", "title": "Report", "body": "Lead"}]
    monkeypatch.setitem(sys.modules, "ddgs", SimpleNamespace(DDGS=FallbackDDGS))
    assert WebTools("duckduckgo").search("annual report")[0]["url"] == "https://issuer.example/report"
    assert backends == ["duckduckgo", "bing"]
