from types import SimpleNamespace

import pytest

from pharma_scope.ai import extract
from pharma_scope.ingest import ingest
from pharma_scope.store import Store


def test_pdf_preserves_physical_pages(tmp_path):
    import pymupdf
    doc = pymupdf.open()
    doc.new_page().insert_text((40, 50), "Cover")
    doc.new_page().insert_text((40, 50), "India revenue 3,000 INR crore consolidated FY2025.")
    path = tmp_path / "report.pdf"
    doc.save(path)
    doc.close()
    store = Store(tmp_path / "db")
    try:
        sid = ingest(store, path, "TEST", "Report", "Issuer", "2025-06-01")
        source = next(s for s in store.sources() if s["id"] == sid)
        assert len(source["pages"]) == 2
        assert "3,000" in source["pages"][1]
        assert source["sha256"]
    finally:
        store.close()


def test_model_output_validated_and_preview_does_not_import(tmp_path, monkeypatch):
    import json
    import openai

    quote = "FY2025 India revenue 3000 INR crore consolidated."
    path = tmp_path / "report.txt"
    path.write_text(quote, encoding="utf-8")
    store = Store(tmp_path / "db")
    try:
        sid = ingest(store, path, "TEST", "Report", "Issuer", "2025-06-01")
        monkeypatch.setenv("OPENAI_API_KEY", "test-not-a-real-key")
        monkeypatch.setenv("PHARMA_MODEL", "test-model")
        row = {"period": 2025, "region": "India", "value": "3000", "currency": "INR", "unit": "crore",
               "basis": "consolidated", "definition": "customer destination", "page": 1, "quote": quote}
        calls = []

        def create(**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(status="completed", output_text=json.dumps({"observations": [row]}))

        monkeypatch.setattr(openai, "OpenAI", lambda **kwargs: SimpleNamespace(responses=SimpleNamespace(create=create)))
        result = extract(store, sid, [1])
        assert result["committed"] is False
        assert store.observations("TEST") == []
        assert calls[0]["store"] is False
        assert calls[0]["text"]["format"]["strict"] is True
        assert "untrusted" in calls[0]["instructions"]
        extract(store, sid, [1], commit=True)
        assert len(store.observations("TEST")) == 1
        row["value"] = "9000"
        with pytest.raises(ValueError, match="does not occur"):
            extract(store, sid, [1], commit=True)
        assert len(store.observations("TEST")) == 1
    finally:
        store.close()


def test_missing_configuration_fails_before_model_call(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    store = Store(tmp_path / "db")
    try:
        with pytest.raises(ValueError, match="Set OPENAI_API_KEY"):
            extract(store, "none", [1])
    finally:
        store.close()
