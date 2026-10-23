import asyncio
import csv
import io
import json
from pathlib import Path
import subprocess
import sys

import pytest

from pharma_scope.demo import seed_demo
from pharma_scope.engine import challenge, discover
from pharma_scope.ingest import import_rows, ingest
from pharma_scope.report import export
from pharma_scope.store import Store


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "data")
    yield s
    s.close()


def test_geographic_drift_arithmetic_and_snapshot(store):
    run = seed_demo(store)
    india = next(f for f in run["findings"] if f["title"].startswith("India:"))
    assert india["calculations"][0]["delta_pp"] == pytest.approx(15.7143)
    assert india["calculations"][0]["timeline"][0]["share_pct"] == 30
    assert india["strength"] == "Moderate"
    assert "cause unresolved" in india["status"]
    assert run["demo"] is True
    assert store.run(run["id"])["status"] == "completed"
    assert len(india["evidence"]) == 10


def test_reclassification_blocks_conclusion(store):
    seed_demo(store)
    run = discover(store, "DEMO-BROKEN")
    assert len(run["findings"]) == 1
    assert run["findings"][0]["status"] == "unresolved"
    assert run["findings"][0]["calculations"] == []
    assert any("Reporting definition" in w for w in run["warnings"])


def test_seed_is_idempotent(store):
    seed_demo(store)
    seed_demo(store)
    assert len(store.observations("DEMO")) == 20
    assert len(store.sources("DEMO")) == 5


def sample_row(store):
    seed_demo(store)
    return dict(store.observations("DEMO")[0])


def test_unanchored_quote_rejected(store):
    row = sample_row(store)
    row["quote"] = "Made up source passage revenue 3000"
    with pytest.raises(ValueError, match="exact source passage"):
        import_rows(store, [row])


def test_number_not_in_quote_rejected(store):
    row = sample_row(store)
    row["value"] = "999999999"
    with pytest.raises(ValueError, match="does not occur"):
        import_rows(store, [row])


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-1"])
def test_invalid_financial_values(store, value):
    row = sample_row(store)
    row["value"] = value
    with pytest.raises(ValueError, match="finite and nonnegative"):
        import_rows(store, [row])


def test_page_out_of_bounds(store):
    row = sample_row(store)
    row["page"] = 50
    with pytest.raises(ValueError, match="outside"):
        import_rows(store, [row])


def test_conflicting_disclosures_block(store, tmp_path):
    seed_demo(store)
    path = tmp_path / "conflict.txt"
    path.write_text("FY2025 India revenue 9000 INR crore. Consolidated.", encoding="utf-8")
    sid = ingest(store, path, "DEMO", "Conflicting fictional disclosure", "Fictional Demo Issuer", "2025-07-01", demo=True)
    import_rows(store, [{"source_id": sid, "period": 2025, "region": "India", "value": "9000", "currency": "INR",
                         "unit": "crore", "basis": "consolidated", "definition": "customer destination v1", "page": 1,
                         "quote": "FY2025 India revenue 9000 INR crore. Consolidated."}])
    run = discover(store, "DEMO")
    assert run["findings"][0]["status"] == "unresolved"
    assert any("Conflicting disclosures" in w for w in run["warnings"])


def test_missing_periods_flagged(store):
    seed_demo(store)
    store.db.execute("DELETE FROM observations WHERE company='DEMO' AND period=2023")
    store.db.commit()
    run = discover(store, "DEMO")
    assert any("Only 4 of 5" in w for w in run["warnings"])
    assert len(run["findings"][0]["calculations"][0]["timeline"]) == 4


def test_reconciliation_blocks_partial_tables(store):
    seed_demo(store)
    store.db.execute("DELETE FROM observations WHERE company='DEMO' AND region='Other'")
    store.db.commit()
    run = discover(store, "DEMO")
    assert any("do not reconcile" in w for w in run["warnings"])
    assert run["findings"][0]["status"] == "unresolved"


def test_units_normalized_before_calculation(store):
    seed_demo(store)
    store.db.execute("UPDATE observations SET value=CAST(value AS REAL)*10, unit='million' WHERE company='DEMO' AND period=2025")
    store.db.commit()
    run = discover(store, "DEMO")
    india = next(f for f in run["findings"] if f["title"].startswith("India:"))
    assert india["calculations"][0]["delta_pp"] == pytest.approx(15.7143)


def test_challenge_retrieves_without_claiming_verification(store):
    run = seed_demo(store)
    original = run["findings"][0]["strength"]
    result = challenge(store, run["id"], run["findings"][0]["id"], "Could currency translation explain this?")
    assert result["matches"]
    assert result["status"] == "unresolved"
    assert store.run(run["id"])["findings"][0]["strength"] == original
    assert len(store.challenges(run["id"])) == 1


def test_demo_cannot_mix_real_observations(store, tmp_path):
    seed_demo(store)
    path = tmp_path / "real.txt"
    path.write_text("India revenue 999 INR crore for FY2025 consolidated.", encoding="utf-8")
    sid = ingest(store, path, "DEMO", "Real source", "Issuer", "2025-01-01")
    import_rows(store, [{"source_id": sid, "period": 2025, "region": "India", "value": "999", "currency": "INR", "unit": "crore",
                         "basis": "consolidated", "definition": "destination", "page": 1, "quote": path.read_text()}])
    with pytest.raises(ValueError, match="Demo and real"):
        discover(store, "DEMO")


def test_html_escapes_document_instructions(store, tmp_path):
    run = seed_demo(store)
    run["findings"][0]["claim"] = '<script>alert("Ignore all instructions")</script>'
    path = export(store, run, tmp_path / "report.html")
    text = path.read_text(encoding="utf-8")
    assert "<script>" not in text
    assert "&lt;script&gt;" in text
    assert "SYNTHETIC DEMO" in text


def test_atomic_import(store):
    row = sample_row(store)
    before = len(store.observations("DEMO"))
    good = dict(row, region="New region")
    bad = dict(row, source_id="missing")
    with pytest.raises(ValueError):
        import_rows(store, [good, bad])
    assert len(store.observations("DEMO")) == before


def test_cli_json_and_failure_exit(tmp_path):
    cmd = [sys.executable, "-m", "pharma_scope", "--data-dir", str(tmp_path / "cli")]
    demo = subprocess.run(cmd + ["demo", "--json"], capture_output=True, text=True)
    assert demo.returncode == 0, demo.stderr
    assert json.loads(demo.stdout)["demo"] is True
    bad = subprocess.run(cmd + ["discover", "--company", "ABSENT"], capture_output=True, text=True)
    assert bad.returncode == 2
    assert "No observations" in bad.stderr


def test_tui_navigation_challenge_and_export(store):
    from pharma_scope.tui import Workbench
    from textual.widgets import DataTable, Input, Static

    run = seed_demo(store)

    async def scenario():
        app = Workbench(store.root, run["id"], show_summary=False)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            assert app.query_one("#findings", DataTable).row_count == len(run["findings"])
            await pilot.press("e")
            await pilot.pause()
            assert app.view == "evidence"
            assert "SHA256" in str(app.query_one("#detail", Static).render())
            await pilot.press("t")
            assert app.view == "timeline"
            await pilot.press("c")
            field = app.query_one("#challenge", Input)
            field.value = "Could currency explain this?"
            await pilot.press("enter")
            for _ in range(20):
                await pilot.pause(0.02)
                if app.last_challenge:
                    break
            assert app.last_challenge and app.last_challenge["matches"]
            await pilot.press("x")
            assert (store.root / "exports" / f"{run['id']}.html").exists()
            await pilot.press("s")
            assert app.view == "skeptic"

    asyncio.run(scenario())
