"""Full graph execution uses fake external providers; never claims live API verification."""
import json
from pathlib import Path

import pytest

from pharma_scope import schemas
from pharma_scope.agent import BudgetExceeded, Limits, ResearchAgent
from pharma_scope.evidence import calculation, extract_facts, validate_finding
from pharma_scope.ingest import ingest
from pharma_scope.report import export
from pharma_scope.store import Store

ISSUER = """Example Pharma Limited develops medicines for India and the US.
FY2021 US revenue was 5000 INR crore on a consolidated customer-destination basis.
FY2025 US revenue was 4500 INR crore on a consolidated customer-destination basis.
On 2023-03-01, Example Pharma reported remediation work at its Plant Alpha facility.
FX effects were not separately disclosed for US revenue.
"""
REGULATOR = """On 2023-01-15, the FDA classified Plant Alpha for Example Pharma as requiring corrective action.
On 2025-06-01, the FDA reported that corrective actions remained under review.
"""


class FakeWeb:
    provider = "test"
    def ready(self):
        pass
    def search(self, query, **kwargs):
        return [{"url": "https://example-pharma.test/report", "title": "Issuer report", "snippet": "Not evidence"},
                {"url": "https://www.fda.gov/test-plant", "title": "Regulator report", "snippet": "Not evidence"}]
    def collect(self, store, company, result, **kwargs):
        regulator = "fda.gov" in result["url"]
        path = store.root / ("regulator.txt" if regulator else "issuer.txt")
        path.write_text(REGULATOR if regulator else ISSUER, encoding="utf-8")
        return ingest(store, path, company, result["title"], "FDA" if regulator else "Example Pharma", "2025-06-01", result["url"])


def fact(quote, **kwargs):
    return {"kind": "business", "statement": quote, "page": 1, "quote": quote, "event_date": "", "fiscal_period": "",
            "metric": "", "value": "", "currency": "", "unit": "", "basis": "", "definition": "", "entity": "Example Pharma", "context_evidence": [], "column_header":{"page":0,"quote":""}, **kwargs}


class FakeModel:
    provider, model, last_usage = "fake", "fake", {}
    def __init__(self):
        self.calls = []
        self.fail_skeptic_once = False
    def generate(self, task, schema, data, **kwargs):
        self.calls.append(task)
        if schema == schemas.PROFILE:
            return {"name": "Example Pharma Limited", "symbol": "EXAMPLE", "official_domain": "example-pharma.test",
                "aliases": [], "subsidiaries": [], "facilities": [], "competitors": [], "uncertainty": [],
                "identity_evidence": [{"url": "https://example-pharma.test/report", "quote": ISSUER.splitlines()[0]}]}
        if schema == schemas.PLAN:
            return {"angles": [{"angle": "regulatory", "question": "Does the event explain revenue?", "significance": "Revenue exposure",
                                "queries": ["Example Pharma revenue regulatory filing"]}], "identity_notes": []}
        if schema == schemas.CLAIM_AUDIT:
            return {"reviews": [{"hypothesis_id": d["hypothesis_id"], "all_claims_supported": True, "track_relevant": True,
                                  "unsupported_claims": [], "reasoning": "Fixture review only, not a live semantic evaluation."} for d in data["drafts"]]}
        if schema == schemas.FACTS:
            if "fda.gov" in data["url"]:
                rows = [fact(REGULATOR.splitlines()[0], kind="regulatory", event_date="2023-01-15")]
                kind, group = "regulator", "US FDA"
            else:
                rows = [fact(ISSUER.splitlines()[i], kind="financial", fiscal_period=str(year), metric="US revenue",
                             value=str(value), currency="INR", unit="crore", basis="consolidated", definition="customer destination")
                        for i, year, value in [(1, 2021, 5000), (2, 2025, 4500)]]
                rows += [fact(ISSUER.splitlines()[3], event_date="2023-03-01"), fact(ISSUER.splitlines()[4])]
                kind, group = "issuer", "Example Pharma"
            return {"facts": rows, "publication_date": "2025-06-01", "origin_group": group, "source_kind": kind, "geography_observations": []}
        facts = data["facts"]
        financial = sorted([f for f in facts if f["kind"] == "financial"], key=lambda f: f["fiscal_period"])
        regulator = next(f for f in facts if f["kind"] == "regulatory")
        fx = next(f for f in facts if "FX effects" in f["quote"])
        support = [financial[0]["id"], financial[-1]["id"], regulator["id"]]
        if schema == schemas.HYPOTHESES:
            return {"hypotheses": [{"id": "draft", "angle": "regulatory", "hypothesis": "Regulatory scrutiny may explain the US revenue decline.",
                "financial_significance": "US revenue declined", "supporting_facts": support, "opposing_facts": [fx["id"]],
                "alternative_explanations": ["Currency translation"], "calculations": [{"id": "us-growth", "operation": "growth_pct",
                    "inputs": [financial[0]["id"], financial[-1]["id"]], "years": 4, "purpose": "US revenue growth"}],
                "followup_queries": ["Example Pharma constant currency US revenue"]}]}
        if schema == schemas.SKEPTIC:
            if self.fail_skeptic_once:
                self.fail_skeptic_once = False
                raise ValueError("Simulated interruption")
            from datetime import date, timedelta
            start = date.fromisoformat(data['as_of']) + timedelta(days=1)
            return {"reviews": [{"hypothesis_id": "hypothesis-1", "verdict": "unresolved", "strongest_counterargument": "FX is not disclosed.",
                "supporting_facts": support, "opposing_facts": [fx["id"]], "alternative_tests": [{"explanation": "Currency translation",
                "outcome": "unresolved", "evidence": [fx["id"]]}], "cause_precedes_effect": False, "chronology_evidence": [], "causal_claim": True,
                "falsification_condition": "Over the next two reported quarters, constant-currency US revenue recovers while remediation remains unchanged.",
                "future_test": {"metric": "constant-currency US revenue growth (%)", "comparison": "above", "threshold": "0",
                                "window_start": start.isoformat(), "window_end": (start + timedelta(days=180)).isoformat(), "source": "Future quarterly issuer results"},
                "followup_queries": ["Example Pharma opposing evidence acquisition FX"], "reasoning": "Timing and a currency-adjusted effect are not established."}]}
        if schema == schemas.FINDINGS:
            def claim(text, refs, calcs=None):
                return {"text": text, "evidence": refs, "calculations": calcs or []}
            return {"findings": [{"hypothesis_id": "hypothesis-1", "discovery": claim("Regulatory scrutiny coincides with a US revenue decline; cause unresolved.", support, ["us-growth"]),
                "why_it_matters": [claim("US revenue declined by 10%.", support[:2], ["us-growth"]),
                    claim("The facility faces regulatory scrutiny.", [regulator["id"]]), claim("FX remains a potential explanation.", [fx["id"]])],
                "timeline": [{"date": "2023-01-15", "description": "FDA classification", "evidence": [regulator["id"]]}],
                "supporting_facts": support, "opposing_facts": [fx["id"]], "counterargument": claim("Currency effects were not separately disclosed.", [fx["id"]]),
                "falsification_condition": "Future constant-currency recovery", "conclusion": "unresolved", "limitations": ["Causation not established"]}]}
        raise AssertionError("Unexpected model stage")


@pytest.fixture
def store(tmp_path):
    store = Store(tmp_path / "data")
    yield store
    store.close()


def test_full_research_graph_and_report(store, tmp_path):
    run = ResearchAgent(store, FakeModel(), FakeWeb(), Limits(seconds=120)).run("EXAMPLE")
    assert run["status"] == "insufficient_evidence"
    assert run["kind"] == "research"
    assert len(run["facts"]) == 5
    assert len(run["findings"]) == 1
    finding = run["findings"][0]
    assert finding["status"] == "unresolved"
    assert finding["strength"] == "Moderate"
    assert finding["calculations"][0]["result"] == "-10.000000"
    assert finding["title"].startswith("Unresolved hypothesis")
    assert store.agent_state(run["id"])["next_stage"] == "done"
    path = export(store, run, tmp_path / "report.html")
    html = path.read_text(encoding="utf-8")
    for section in ["Why it matters", "Timeline", "Strongest counterargument", "Evidence strength", "Evidence register"]:
        assert section in html
    assert '<a class="ref" href="#fact-' in html
    assert "<table>" in html


def test_resume_keeps_sources_and_completed_work(store):
    model = FakeModel()
    model.fail_skeptic_once = True
    with pytest.raises(ValueError, match="Simulated"):
        ResearchAgent(store, model, FakeWeb(), Limits(seconds=120)).run("EXAMPLE")
    state_id = store.db.execute("SELECT id FROM agent_states").fetchone()[0]
    state = store.agent_state(state_id)
    assert state["next_stage"] == "skeptic"
    calls_before = len(model.calls)
    run = ResearchAgent(store, model, FakeWeb(), Limits(seconds=120)).run(resume=state_id)
    assert run["id"] == state_id
    assert len(store.sources("EXAMPLE")) == 2
    assert len(model.calls) - calls_before <= 4


def test_budget_is_enforced_and_saved(store):
    with pytest.raises(BudgetExceeded):
        ResearchAgent(store, FakeModel(), FakeWeb(), Limits(model_calls=1, seconds=120)).run("EXAMPLE")
    state_id = store.db.execute("SELECT id FROM agent_states").fetchone()[0]
    state = store.agent_state(state_id)
    assert state["status"] == "budget_exhausted"
    assert state["usage"]["model_calls"] == 1
    run = ResearchAgent(store, FakeModel(), FakeWeb(), Limits(model_calls=30, seconds=120)).run(resume=state_id)
    assert run["status"] == "insufficient_evidence"


def test_same_issuer_never_counts_as_independent(store):
    run = ResearchAgent(store, FakeModel(), FakeWeb(), Limits(seconds=120)).run("EXAMPLE")
    state = store.agent_state(run["id"])
    review = state["reviews"][0]
    review["verdict"] = "supported"
    review["causal_claim"] = False
    review["alternative_tests"] = []
    # Reclassify regulator source as a republished issuer release.
    sources = {s["id"]: {**s, "source_kind": "issuer", "origin_group": "Example Pharma"} for s in run["sources"]}
    model = FakeModel()
    draft = model.generate("", schemas.FINDINGS, {"facts": run["facts"]})["findings"][0]
    draft["conclusion"] = "supported"
    finding = validate_finding(draft, review, state["hypotheses"][0], {f["id"]: f for f in run["facts"]}, sources, state["calculations"], state["profile"], state['as_of'])
    assert finding["status"] == "unresolved"
    assert finding["strength"] == "Weak"


def test_hallucinated_quote_and_value_rejected():
    source = {"id": "source", "pages": [ISSUER]}
    rows = [fact("Invented quote says US revenue 9999 INR crore", value="9999", metric="US revenue", unit="crore", basis="consolidated", definition="customer destination", fiscal_period="2025")]
    accepted, errors = extract_facts(source, rows)
    assert accepted == [] and errors


def test_failed_search_does_not_discard_readable_evidence(store):
    class IntermittentWeb(FakeWeb):
        def __init__(self):
            self.count = 0
        def search(self, query, **kwargs):
            self.count += 1
            if self.count > 1:
                raise ValueError("Search temporarily unavailable")
            return super().search(query, **kwargs)
    run = ResearchAgent(store, FakeModel(), IntermittentWeb(), Limits(seconds=120)).run("EXAMPLE")
    assert run["facts"]
    assert run["status"] == "insufficient_evidence"
    assert any("Coverage is incomplete" in warning for warning in run["warnings"])


def test_invalid_extraction_gets_one_source_grounded_repair(store):
    class RepairModel(FakeModel):
        def __init__(self):
            super().__init__()
            self.damaged = False
        def generate(self, task, schema, data, **kwargs):
            result = super().generate(task, schema, data, **kwargs)
            if schema == schemas.FACTS and not self.damaged:
                self.damaged = True
                for row in result["facts"]:
                    row["quote"] = "Invented passage not in the document"
            return result
    model = RepairModel()
    run = ResearchAgent(store, model, FakeWeb(), Limits(seconds=120)).run("EXAMPLE")
    assert run["facts"]
    assert any("previous extraction failed" in task.lower() for task in model.calls)


def test_calculations_reject_incompatible_basis():
    a = fact(ISSUER.splitlines()[1], value="5000", metric="US revenue", unit="crore", currency="INR", basis="consolidated", definition="destination", fiscal_period="2021")
    b = {**a, "value": "4500", "basis": "standalone", "fiscal_period": "2025"}
    with pytest.raises(ValueError, match="incompatible basis"):
        calculation({"operation": "growth_pct", "inputs": ["a", "b"], "years": 4}, {"a": a, "b": b})


def test_html_does_not_execute_source_instructions(store, tmp_path):
    run = ResearchAgent(store, FakeModel(), FakeWeb(), Limits(seconds=120)).run("EXAMPLE")
    run["facts"][0]["quote"] = '<script>send secrets</script>'
    path = export(store, run, tmp_path / "safe.html")
    html = path.read_text(encoding="utf-8")
    assert "<script>" not in html
    assert 'Earlier Claims Withheld' in html
    assert 'quote not found' in html


def test_collected_sources_remain_visible_without_validated_facts(store):
    from pharma_scope.research_report import html
    run = ResearchAgent(store, FakeModel(), FakeWeb(), Limits(seconds=120)).run("EXAMPLE")
    run.update(facts=[], findings=[])
    duplicate = {**run['sources'][0], 'id': 'duplicate', 'title': '<script>Repeated</script>'}
    run['sources'].append(duplicate)
    report = html(run)
    assert 'Collected sources' in report
    assert 'https://example-pharma.test/report' in report
    assert 'No accepted facts; not supporting evidence' in report
    assert 'No extracted facts passed validation' in report
    assert 'Repeated file content' in report
    assert '<script>' not in report
