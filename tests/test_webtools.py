import socket

import pytest

from pharma_scope.webtools import public_url, WebTools


@pytest.mark.parametrize("url", ["file:///etc/passwd", "http://localhost/a", "http://127.0.0.1/a", "http://user:secret@example.com/", "http://example.com:1234/a"])
def test_non_public_urls_blocked(url):
    with pytest.raises(ValueError):
        public_url(url)


def test_private_dns_blocked(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [(None, None, None, None, ("10.0.0.1", 443))])
    with pytest.raises(ValueError, match="Private"):
        public_url("https://example.com/report")


def test_missing_search_credentials_actionable(monkeypatch):
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    with pytest.raises(ValueError, match="BRAVE_API_KEY"):
        WebTools("brave").ready()


def test_follow_official_report_links_only(tmp_path):
    from pharma_scope.store import Store
    store = Store(tmp_path / "data")
    try:
        page = tmp_path / "index.html"
        page.write_text('<a href="/annual-report.pdf">Annual report</a><a href="https://elsewhere.example/report.pdf">Report</a>', encoding="utf-8")
        store.metadata = lambda sid: {"original_archive": str(page)}
        leads = WebTools().report_links(store, [{"id": "s", "url": "https://issuer.example/investors"}], "issuer.example")
        assert [lead["url"] for lead in leads] == ["https://issuer.example/annual-report.pdf"]
    finally:
        store.close()
