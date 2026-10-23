"""Public web collection. Search snippets are leads, not evidence."""
from __future__ import annotations

from datetime import date
import ipaddress
import json
import os
from pathlib import Path
import socket
from urllib.parse import urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup
import httpx

from .ingest import ingest
from .store import digest, now


def public_url(url):
    parts = urlparse(url)
    if parts.scheme not in {"https", "http"} or not parts.hostname or parts.username or parts.password:
        raise ValueError("Only unauthenticated public HTTP(S) URLs are allowed.")
    if parts.port and parts.port not in {80, 443}:
        raise ValueError("Nonstandard URL ports are not allowed.")
    addresses = socket.getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80), type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError("Private, loopback and reserved destinations are not allowed.")
    return urlunparse(parts._replace(fragment=""))


class WebTools:
    def __init__(self, provider=None):
        self.provider = provider or os.getenv("PHARMA_SEARCH_PROVIDER", "brave")

    def ready(self):
        if self.provider == "duckduckgo":
            try:
                from ddgs import DDGS
            except ImportError:
                raise ValueError('Install account-free search: python -m pip install -e ".[search]"') from None
            return
        variable = "BRAVE_API_KEY" if self.provider == "brave" else "TAVILY_API_KEY"
        if self.provider not in {"brave", "tavily"} or not os.getenv(variable):
            raise ValueError("Choose duckduckgo for account-free search, or configure BRAVE_API_KEY/TAVILY_API_KEY for the selected search provider.")

    def search(self, query, count=5, timeout=25):
        self.ready()
        if self.provider == "duckduckgo":
            from ddgs import DDGS
            last_error = "NoResults"
            for backend in ["duckduckgo", "bing"]:
                try:
                    # Two bounded public backends share this logical query timeout.
                    records = DDGS(timeout=max(1, int(timeout / 2))).text(query[:400], max_results=min(count, 10), backend=backend)
                    results = [{"url": r.get("href") or r.get("url", ""), "title": r.get("title", ""),
                                "snippet": r.get("body", "")} for r in records if r.get("href") or r.get("url")]
                    if results:
                        return results
                except Exception as exc:
                    last_error = type(exc).__name__
            raise ValueError(f"Account-free search unavailable ({last_error}); it may be rate-limited. Retry later or use another provider.") from None
        try:
            if self.provider == "brave":
                response = httpx.get("https://api.search.brave.com/res/v1/web/search", params={"q": query[:400], "count": min(count, 10)},
                    headers={"Accept": "application/json", "X-Subscription-Token": os.environ["BRAVE_API_KEY"]}, timeout=timeout)
                if response.status_code != 200:
                    raise ValueError(f"Brave search failed (HTTP {response.status_code}).")
                records = response.json().get("web", {}).get("results", [])
                return [{"url": r["url"], "title": r.get("title", ""), "snippet": r.get("description", "")} for r in records]
            response = httpx.post("https://api.tavily.com/search", headers={"Authorization": "Bearer " + os.environ["TAVILY_API_KEY"]},
                json={"query": query[:400], "max_results": min(count, 10), "search_depth": "basic", "include_answer": False}, timeout=timeout)
            if response.status_code != 200:
                raise ValueError(f"Tavily search failed (HTTP {response.status_code}).")
            return [{"url": r["url"], "title": r.get("title", ""), "snippet": r.get("content", "")} for r in response.json().get("results", [])]
        except httpx.HTTPError as exc:
            raise ValueError(f"Search network request failed ({type(exc).__name__}).") from None

    def download(self, url, timeout=25, max_bytes=20000000):
        # Validate every redirect; never forward API credentials or cookies to evidence hosts.
        with httpx.Client(headers={"User-Agent": "PHARMA-SCOPE/0.2 public-financial-research"}, follow_redirects=False, timeout=timeout) as client:
            for _ in range(6):
                url = public_url(url)
                try:
                    with client.stream("GET", url) as response:
                        if response.status_code in {301, 302, 303, 307, 308}:
                            url = urljoin(url, response.headers.get("location", ""))
                            continue
                        if response.status_code != 200:
                            raise ValueError(f"Source retrieval failed (HTTP {response.status_code}).")
                        content = bytearray()
                        for chunk in response.iter_bytes():
                            content.extend(chunk)
                            if len(content) > max_bytes:
                                raise ValueError("Source exceeds download size limit.")
                        return {"url": url, "data": bytes(content), "content_type": response.headers.get("content-type", "")}
                except httpx.HTTPError as exc:
                    raise ValueError(f"Source network request failed ({type(exc).__name__}).") from None
        raise ValueError("Too many source redirects.")

    def report_links(self, store, sources, official_domain):
        domain = official_domain.lower().removeprefix("www.")
        if not domain:
            return []
        leads, seen = [], set()
        for source in sources:
            metadata = store.metadata(source["id"])
            original = Path(metadata.get("original_archive", ""))
            if original.suffix != ".html" or not original.is_file():
                continue
            host = (urlparse(source["url"]).hostname or "").removeprefix("www.")
            if host != domain and not host.endswith("." + domain):
                continue
            soup = BeautifulSoup(original.read_bytes(), "html.parser")
            for link in soup.find_all("a", href=True):
                url = urljoin(source["url"], link["href"])
                parts = urlparse(url)
                target = (parts.hostname or "").removeprefix("www.")
                if parts.scheme not in {"http", "https"} or (target != domain and not target.endswith("." + domain)):
                    continue
                label = link.get_text(" ", strip=True)
                if not parts.path.lower().endswith(".pdf") or not any(word in (label + " " + parts.path).lower() for word in ["annual", "report", "result", "presentation"]):
                    continue
                if url not in seen:
                    seen.add(url)
                    leads.append({"url": url, "title": label or "Official company disclosure", "snippet": "Linked from official report index"})
        return leads

    def collect(self, store, company, result, timeout=25):
        downloaded = self.download(result["url"], timeout)
        raw, url = downloaded["data"], downloaded["url"]
        raw_hash = digest(raw)
        pdf = raw.startswith(b"%PDF")
        suffix = ".pdf" if pdf else ".html"
        original = store.archive / (raw_hash + suffix)
        original.write_bytes(raw)
        published, title = "", result.get("title", "") or urlparse(url).hostname
        if pdf:
            path = original
        else:
            if "html" not in downloaded["content_type"] and "text/" not in downloaded["content_type"]:
                raise ValueError("Unsupported source content type.")
            soup = BeautifulSoup(raw, "html.parser")
            if soup.title:
                title = soup.title.get_text(" ", strip=True)
            date_tag = soup.find("meta", attrs={"property": "article:published_time"}) or soup.find("meta", attrs={"name": "date"})
            if date_tag:
                candidate = date_tag.get("content", "")[:10]
                try:
                    published = date.fromisoformat(candidate).isoformat()
                except ValueError:
                    pass
            for node in soup(["script", "style", "nav", "footer", "header", "noscript", "form"]):
                node.decompose()
            text = soup.get_text("\n", strip=True)
            if len(text.strip()) < 150:
                raise ValueError("Source has insufficient readable text (possibly requires JavaScript or is blocked).")
            path = store.archive / (raw_hash + ".txt")
            path.write_text(text, encoding="utf-8")
        sid = ingest(store, path, company, title[:400], urlparse(url).hostname, published, url)
        previous = store.metadata(sid)
        store.metadata(sid, {**previous, "retrieved_at": now(), "original_sha256": raw_hash, "original_archive": str(original),
                            "canonical_url": url, "publication_date_verified": bool(published), "search_lead": result.get("snippet", "")})
        return sid
