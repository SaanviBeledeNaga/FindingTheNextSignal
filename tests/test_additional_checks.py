from copy import deepcopy

import pytest

from pharma_scope import schemas
from pharma_scope.agent import Limits, ResearchAgent
from pharma_scope.evidence import calculation, validate_finding, date_in_quote
from pharma_scope.store import Store
from test_agent import FakeModel, FakeWeb, ISSUER, fact


def test_supported_graph_path_and_no_forced_strong_rating(tmp_path):
    class ObservationalModel(FakeModel):
        def generate(self, task, schema, data, **kwargs):
            result = super().generate(task, schema, data, **kwargs)
            if schema == schemas.SKEPTIC:
                for review in result["reviews"]:
                    review["verdict"] = "supported"
                    review["causal_claim"] = False
                    review["alternative_tests"] = []
                    review["followup_queries"] = []
            if schema == schemas.FINDINGS:
                result["findings"][0]["conclusion"] = "supported"
            return result
    store = Store(tmp_path / "db")
    try:
        run = ResearchAgent(store, ObservationalModel(), FakeWeb(), Limits(seconds=120)).run("EXAMPLE")
        assert run["status"] == "completed"
        assert run["findings"][0]["status"] == "supported"
        assert run["findings"][0]["strength"] == "Moderate"  # opposing fact remains
    finally:
        store.close()


def test_bad_claim_number_with_real_citations_is_withheld(tmp_path):
    class InventedNumber(FakeModel):
        def generate(self, task, schema, data, **kwargs):
            result = super().generate(task, schema, data, **kwargs)
            if schema == schemas.FINDINGS:
                result["findings"][0]["why_it_matters"][0]["text"] = "US revenue declined by 99%."
            return result
    store = Store(tmp_path / "db")
    try:
        run = ResearchAgent(store, InventedNumber(), FakeWeb(), Limits(seconds=120)).run("EXAMPLE")
        assert run["findings"] == []
        assert any("ungrounded number" in w for w in run["warnings"])
    finally:
        store.close()


def test_cagr_years_must_match_periods():
    a = fact(ISSUER.splitlines()[1], value="5000", metric="US revenue", unit="crore", currency="INR", basis="consolidated", definition="destination", fiscal_period="2021")
    b = {**a, "value": "4500", "fiscal_period": "2025"}
    with pytest.raises(ValueError, match="year interval"):
        calculation({"operation": "cagr_pct", "inputs": ["a", "b"], "years": 2}, {"a": a, "b": b})


def test_financial_periods_cannot_run_backwards():
    a = fact(ISSUER.splitlines()[1], value="5000", metric="US revenue", unit="crore", currency="INR", basis="consolidated", definition="destination", fiscal_period="2025")
    b = {**a, "value": "4500", "fiscal_period": "2021"}
    with pytest.raises(ValueError, match="progress forward"):
        calculation({"operation": "growth_pct", "inputs": ["a", "b"], "years": 4}, {"a": a, "b": b})


def test_full_date_must_be_supported():
    assert date_in_quote("2023-01-15", "On January 15, 2023, the FDA announced an inspection.")
    assert date_in_quote("2023-01-15", "On 2023-01-15, the FDA announced an inspection.")
    assert not date_in_quote("2023-01-15", "In 2023, the FDA announced an inspection.")
