"""Entirely fictional data, including deliberate reporting drift in DEMO-BROKEN."""
from pathlib import Path

from .engine import discover
from .ingest import import_rows, ingest


def seed_demo(store):
    folder = store.root / "demo-inputs"
    folder.mkdir(exist_ok=True)
    for company, broken in [("DEMO", False), ("DEMO-BROKEN", True)]:
        for i, year in enumerate(range(2021, 2026)):
            total, india, us = 10000 + i * 1000, 3000 + i * 850, 5000 - i * 100
            values = {"India": india, "US": us, "Other": total - india - us, "Total": total}
            definition = "customer destination v2" if broken and year >= 2024 else "customer destination v1"
            quotes = {r: f"FY{year} | {r} | revenue {v} INR crore | consolidated | {definition}." for r, v in values.items()}
            text = (f"SYNTHETIC DEMO - NOT REAL COMPANY DATA\n{company} Annual Report FY{year}\n\n"
                    + "\n".join(quotes.values())
                    + "\n\nRevenue is translated at average exchange rates. Constant currency geographic figures are not disclosed. "
                      "A change in reported revenue mix does not establish a strategy change.\n")
            if broken and year >= 2024:
                text += "\nGeographic reporting definition changed in FY2024; prior periods have not been recast.\n"
            path = folder / f"{company}-{year}.txt"
            path.write_text(text, encoding="utf-8")
            sid = ingest(store, path, company, f"Fictional annual report FY{year}", "Fictional Demo Issuer",
                         f"{year}-06-01", demo=True)
            import_rows(store, [{"source_id": sid, "period": year, "region": r, "value": v, "currency": "INR",
                                 "unit": "crore", "basis": "consolidated", "definition": definition,
                                 "page": 1, "quote": quotes[r]} for r, v in values.items()])
    return discover(store, "DEMO")
