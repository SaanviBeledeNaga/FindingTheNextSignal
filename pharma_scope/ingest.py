from __future__ import annotations

import csv
import io
import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlparse

from .store import Store, digest, uid


def read_pages(path: Path) -> list[str]:
    if path.suffix.lower() == ".pdf":
        try:
            import pymupdf
        except ImportError as exc:
            raise ValueError("PDF support needs: python -m pip install -e .") from exc
        with pymupdf.open(path) as doc:
            pages = [page.get_text(sort=True) for page in doc]
        if not any(p.strip() for p in pages):
            raise ValueError("No PDF text found; OCR scanned reports before ingestion.")
        return pages
    if path.suffix.lower() not in {".txt", ".md"}:
        raise ValueError("Sources must be .pdf, .txt or .md; use form-feed for text page breaks.")
    return path.read_text(encoding="utf-8-sig").split("\f")


def ingest(store: Store, path: Path, company: str, title: str, publisher: str,
           published: str, url: str = "", demo=False) -> str:
    if not all(s.strip() for s in (company, title, publisher)):
        raise ValueError("Company, title and publisher must be nonempty.")
    if published:
        date.fromisoformat(published)
    if url and urlparse(url).scheme not in {"http", "https"}:
        raise ValueError("Source URLs must use http or https.")
    data = path.read_bytes()
    if len(data) > 60_000_000:
        raise ValueError("Source exceeds the 60 MB limit.")
    sha = digest(data)
    company = company.upper()
    existing = store.db.execute("SELECT id,demo FROM sources WHERE company=? AND sha256=?", (company, sha)).fetchone()
    if existing:
        if bool(existing["demo"]) != bool(demo):
            raise ValueError("The same source cannot mix demo and real provenance.")
        return existing["id"]
    pages = read_pages(path)
    archive = store.archive / (sha + path.suffix.lower())
    archive.write_bytes(data)
    source_id = uid("src")
    store.db.execute("INSERT INTO sources VALUES (?,?,?,?,?,?,?,?,?,?)", (
        source_id, company, title, publisher, published, url, sha, str(archive), json.dumps(pages), int(demo)))
    store.db.commit()
    return source_id


def norm(text):
    return " ".join(str(text).split()).casefold()


def validate_observation(row, source):
    required = ["period", "region", "value", "currency", "unit", "basis", "definition", "page", "quote"]
    for key in required:
        if key not in row or not str(row[key]).strip():
            raise ValueError(f"Missing observation field: {key}")
    try:
        value = Decimal(str(row["value"]))
    except InvalidOperation as exc:
        raise ValueError("Observation value must be a decimal number without commas.") from exc
    if not value.is_finite() or value < 0:
        raise ValueError("Revenue must be finite and nonnegative.")
    page, period = int(row["page"]), int(row["period"])
    if not 1900 <= period <= 2200:
        raise ValueError("period must be the fiscal end year, e.g. 2025.")
    if not 1 <= page <= len(source["pages"]):
        raise ValueError("Page is outside the source document.")
    quote = str(row["quote"])
    if len(norm(quote)) < 12 or norm(quote) not in norm(source["pages"][page - 1]):
        raise ValueError("Quote must be an exact source passage (whitespace may differ).")
    # A model or spreadsheet cannot attach an unrelated number to a real quote.
    numbers = re.findall(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?", quote)
    if value not in [Decimal(n.replace(",", "")) for n in numbers]:
        raise ValueError("Observation value does not occur in its evidence quote.")
    if str(row["basis"]).lower() not in {"consolidated", "standalone"}:
        raise ValueError("basis must be consolidated or standalone.")
    if str(row["currency"]).upper() not in {"INR", "USD", "EUR", "GBP", "JPY"}:
        raise ValueError("Unsupported currency; use INR, USD, EUR, GBP or JPY.")
    if str(row["unit"]).lower() not in {"units", "thousand", "lakh", "million", "crore", "billion"}:
        raise ValueError("Unsupported unit.")
    return (uid("obs"), source["id"], source["company"], period, str(row["region"]).strip(), str(value),
            str(row["currency"]).upper(), str(row["unit"]).lower(), str(row["basis"]).lower(),
            str(row["definition"]).strip(), page, quote, source["demo"])


def import_rows(store: Store, rows: list[dict]) -> int:
    sources = {s["id"]: s for s in store.sources()}
    validated = []
    for i, row in enumerate(rows, 1):
        if row.get("source_id") not in sources:
            raise ValueError(f"Row {i}: unknown source_id.")
        try:
            validated.append(validate_observation(row, sources[row["source_id"]]))
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Row {i}: {exc}") from exc
    before = store.db.total_changes
    with store.db:
        for values in validated:
            # Never overwrite an already recorded financial observation silently.
            existing = store.db.execute(
                "SELECT value,currency,unit,page,quote FROM observations WHERE source_id=? AND period=? AND region=? AND basis=? AND definition=?",
                (values[1], values[3], values[4], values[8], values[9])).fetchone()
            if existing:
                if tuple(existing) != (values[5], values[6], values[7], values[10], values[11]):
                    raise ValueError("Conflicting observation for the same disclosure; import a distinct restated source.")
                continue
            store.db.execute("INSERT INTO observations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", values)
    return store.db.total_changes - before


def import_csv(store, path):
    return import_rows(store, list(csv.DictReader(io.StringIO(Path(path).read_text(encoding="utf-8-sig")))))
