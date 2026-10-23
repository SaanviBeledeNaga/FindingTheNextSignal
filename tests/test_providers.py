from types import SimpleNamespace

import httpx
import pytest

from pharma_scope.providers import Model
from pharma_scope.schemas import obj, S
from pharma_scope.webtools import WebTools


def test_gemini_structured_request_contract(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "unit-test-key")
    monkeypatch.setenv("PHARMA_MODEL", "test-model")
    calls = []
    def post(url, **kwargs):
        calls.append((url, kwargs))
        return httpx.Response(200, json={"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": '{"value":"verified"}'}]}}], "usageMetadata": {"totalTokenCount": 5}})
    monkeypatch.setattr(httpx, "post", post)
    model = Model("gemini")
    result = model.generate("Extract facts", obj(value=S), {"text": "source"})
    assert result == {"value": "verified"}
    assert calls[0][0].endswith("models/test-model:generateContent")
    assert calls[0][1]["headers"]["x-goog-api-key"] == "unit-test-key"
    assert calls[0][1]["json"]["generationConfig"]["responseJsonSchema"] == obj(value=S)
    assert model.last_usage["totalTokenCount"] == 5


def test_model_errors_do_not_echo_credentials(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "private-test-sentinel")
    monkeypatch.setenv("PHARMA_MODEL", "test-model")
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: httpx.Response(401, json={"secret": "private-test-sentinel"}))
    with pytest.raises(ValueError) as error:
        Model("gemini").generate("test", obj(value=S), {})
    assert "private-test-sentinel" not in str(error.value)


def test_brave_search_results_are_only_leads(monkeypatch):
    monkeypatch.setenv("BRAVE_API_KEY", "unit-test-key")
    calls = []
    def get(url, **kwargs):
        calls.append((url, kwargs))
        return httpx.Response(200, json={"web": {"results": [{"url": "https://example.com/report", "title": "Report", "description": "Lead"}]}})
    monkeypatch.setattr(httpx, "get", get)
    results = WebTools("brave").search("Company annual report")
    assert results[0]["snippet"] == "Lead"
    assert "pages" not in results[0]
    assert calls[0][1]["headers"]["X-Subscription-Token"] == "unit-test-key"
