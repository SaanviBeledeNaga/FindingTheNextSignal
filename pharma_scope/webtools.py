"""Public web collection. Search snippets are leads, not evidence."""
from __future__ import annotations

from datetime import date
import ipaddress
import json
import os
import re
from pathlib import Path
import socket
import time
from urllib.parse import urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup
import httpx

from .ingest import ingest
from .store import digest, now

REPORT_DIRECTORIES = {'annualreports.com', 'companiesmarketcap.com'}
NON_ISSUER_DOMAINS = REPORT_DIRECTORIES | {'scribd.com','trendlyne.com','moneycontrol.com','screener.in',
    'financialfilings.com','marketscreener.com','nseindia.com','bseindia.com','sec.gov','fda.gov'}


def host_is(host, domain):
    return host == domain or host.endswith('.' + domain)


def document_year(result):
    text = result.get('title','') + ' ' + urlparse(result.get('url','')).path
    years = [int(y) for y in re.findall(r'(?<!\d)20\d{2}(?!\d)', text)]
    return max(years, default=0)


def disclosure_score(result):
    """Prioritize substantive disclosures; a filename is a retrieval hint, never evidence."""
    text = (result.get("title", "") + " " + result.get("url", "")).lower()
    score = 5 if urlparse(result.get("url", "")).path.lower().endswith(".pdf") else 0
    score += 8 * bool(re.search(r"annual|financial.result|financial.statement|investor.presentation|earnings.release|press.release", text))
    score += 4 * bool(re.search(r"annual", text))
    score += 3 * bool(re.search(r"revenue|segment|quarter|presentation|result|report", text))
    score -= 18 * bool(re.search(r"intimation|invitation|call.schedule|earnings.call.notice|client.challenge", text))
    years = [int(y) for y in re.findall(r"(?<!\d)20\d{2}(?!\d)", text) if int(y) <= date.today().year]
    return score, max(years, default=0)


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

    def download(self, url, timeout=25, max_bytes=60000000):
        # Validate every redirect; never forward API credentials or cookies to evidence hosts.
        started = time.monotonic()
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
                        size = response.headers.get('content-length','')
                        if size.isdigit() and int(size) > max_bytes:
                            raise ValueError('Source exceeds the 60 MB full-document download limit.')
                        content = bytearray()
                        for chunk in response.iter_bytes():
                            if time.monotonic() - started > timeout:
                                raise ValueError('Source download exceeded its total time budget.')
                            content.extend(chunk)
                            if len(content) > max_bytes:
                                raise ValueError("Source exceeds download size limit.")
                        return {"url": url, "data": bytes(content), "content_type": response.headers.get("content-type", "")}
                except httpx.HTTPError as exc:
                    raise ValueError(f"Source network request failed ({type(exc).__name__}).") from None
        raise ValueError("Too many source redirects.")

    def issuer_links(self, store, sources):
        """Explicit website hyperlinks are discovery leads; a directory is never the issuer."""
        leads = []
        for source in sources:
            path = Path(store.metadata(source['id']).get('original_archive',''))
            if path.suffix != '.html' or not path.is_file():
                continue
            for a in BeautifulSoup(path.read_bytes(),'html.parser').find_all('a',href=True):
                if not re.fullmatch(r'(?:visit\s+)?(?:official\s+|company\s+)?(?:web\s?site)(?:\s*[↗»])?',a.get_text(' ',strip=True),re.I):
                    continue
                url = urljoin(source['url'],a['href'])
                host = (urlparse(url).hostname or '').lower().removeprefix('www.')
                if urlparse(url).scheme in {'https','http'} and host and not any(host_is(host,d) for d in NON_ISSUER_DOMAINS):
                    leads.append({'url':url,'title':'Issuer website linked by company directory','linked_from':source['url'],'snippet':'Website hyperlink; not independent evidence'})
        return leads

    def report_links(self, store, sources, official_domain):
        domain = official_domain.lower().removeprefix("www.")
        leads, seen = [], set()
        for source in sources:
            metadata = store.metadata(source["id"])
            original = Path(metadata.get("original_archive", ""))
            if original.suffix != ".html" or not original.is_file():
                continue
            host = (urlparse(source["url"]).hostname or "").removeprefix("www.")
            directory = any(host_is(host,d) for d in REPORT_DIRECTORIES)
            official = bool(domain and host_is(host,domain))
            if not official and not directory:
                continue
            soup = BeautifulSoup(original.read_bytes(), "html.parser")
            for link in soup.find_all(["a", "iframe", "object"]):
                href = link.get("href") or link.get("src") or link.get("data") or link.get("data-url")
                if not href:
                    continue
                url = urljoin(source["url"], href)
                parts = urlparse(url)
                target = (parts.hostname or "").removeprefix("www.")
                if directory and parts.path.lower().endswith('.pdf') and parts.query == 'save':
                    # Catalogs offer view/download links to the same file. One
                    # request is sufficient; repeated copies add no corroboration.
                    url = urlunparse(parts._replace(query='',fragment=''))
                    parts = urlparse(url)
                if parts.scheme not in {"http", "https"}:
                    continue
                label = link.get_text(" ", strip=True)
                is_pdf = parts.path.lower().endswith(".pdf")
                same_domain = bool(domain and host_is(target,domain))
                text = (label + " " + parts.path).lower()
                financial = bool(re.search(r"annual|financial|result|presentation|press.release|quarter", text))
                parent_financial = bool(re.search(r"annual|financial|result|presentation", source.get("title", ""), re.I))
                # External CDN PDFs are allowed only when linked by a fetched official page.
                # Off-domain HTML navigation is not followed. Every download still validates public URLs.
                if directory:
                    # A company directory may link a full report copy, never unrelated HTML.
                    allowed = is_pdf and (financial or parent_financial)
                else:
                    allowed = (is_pdf and (financial or parent_financial)) or (same_domain and financial)
                if not allowed:
                    continue
                if url not in seen:
                    seen.add(url)
                    leads.append({"url": url, "title": label or "Linked company disclosure", "snippet": "Linked from company report directory" if directory else "Linked from issuer report index",
                                  "linked_from": source["url"]})
        return sorted(leads, key=disclosure_score, reverse=True)

    def is_report_index(self, store, source):
        """Avoid spending extraction calls on link directories with no financial discussion."""
        path = Path(store.metadata(source['id']).get('original_archive', ''))
        if path.suffix != '.html' or not path.is_file():
            return False
        soup = BeautifulSoup(path.read_bytes(), 'html.parser')
        pdf_links = sum(urlparse(a.get('href', '')).path.lower().endswith('.pdf') for a in soup.find_all('a', href=True))
        body = ' '.join(source['pages'])
        figures = re.search(r"(?:revenue|profit|sales|margin)[^\n]{0,100}(?:million|crore|billion|\d\s*%)", body, re.I)
        return pdf_links >= 3 and not figures

    def collect(self, store, company, result, timeout=25):
        downloaded = self.download(result["url"], timeout)
        return self.collect_downloaded(store, company, result, downloaded)

    def collect_downloaded(self, store, company, result, downloaded, parse_timeout=None):
        """Commit one completed download on the owning SQLite thread."""
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
        sid = ingest(store, path, company, title[:400], urlparse(url).hostname, published, url, parse_timeout=parse_timeout)
        previous = store.metadata(sid)
        store.metadata(sid, {**previous, "retrieved_at": now(), "original_sha256": raw_hash, "original_archive": str(original),
                            "canonical_url": url, "publication_date_verified": bool(published), "search_lead": result.get("snippet", ""),
                            "linked_from": result.get("linked_from", "")})
        return sid
