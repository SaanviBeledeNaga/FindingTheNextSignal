"""Regressions for the scheduling-only Sun Pharma report and real table layouts."""
import pytest

from pharma_scope import schemas
from pharma_scope.agent import ResearchAgent, Limits
from pharma_scope.evidence import extract_facts, validate_future_test
from pharma_scope.store import Store
from pharma_scope.webtools import WebTools, disclosure_score
from test_agent import FakeModel, FakeWeb, fact, ISSUER


TABLE = """Consolidated Statement of Profit and Loss
Amounts in INR million
Year ended March 31, 2025     Year ended March 31, 2024
Revenue from operations      525.0     480.0
"""


def table_fact():
    return fact("Revenue from operations      525.0     480.0", kind="financial", value="525.0", metric="Revenue from operations",
                fiscal_period="FY2025", currency="INR", unit="million", basis="consolidated", definition="revenue from operations",
                context_evidence=[{"page": 1, "quote": "Amounts in INR million"},
                                  {"page": 1, "quote": "Year ended March 31, 2025     Year ended March 31, 2024"},
                                  {"page": 1, "quote": "Consolidated Statement of Profit and Loss"}])


def test_table_row_uses_separately_anchored_headers():
    source = {"id": "s", "pages": [TABLE]}
    row = table_fact()
    accepted, errors = extract_facts(source, [row])
    assert not errors and accepted[0]["value"] == "525.0"
    assert accepted[0]["context_evidence"] == row["context_evidence"]


def test_original_unit_case_is_normalized_without_inventing_a_unit():
    row = table_fact()
    row['unit'] = 'Million'
    accepted, errors = extract_facts({'id': 's', 'pages': [TABLE]}, [row])
    assert not errors and accepted[0]['unit'] == 'million'
    row['unit'] = 'widgets'
    assert not extract_facts({'id': 's', 'pages': [TABLE]}, [row])[0]


def test_income_statement_survives_keyword_dense_notes(tmp_path):
    store = Store(tmp_path / 'data')
    try:
        source = {'pages': ['Company cover'] + ['geographic segment revenue from operations margin ' * 20] * 14 +
                          ['Consolidated Statement of Profit and Loss\nRevenue from operations 525 480']}
        pages = ResearchAgent(store, FakeModel(), FakeWeb()).selected_pages(source)
        assert 1 in [p['page'] for p in pages] and 16 in [p['page'] for p in pages]
        assert len(pages) <= 10
    finally:
        store.close()


def test_invented_table_context_is_rejected():
    row = table_fact()
    row["context_evidence"][0]["quote"] = "Amounts in USD billion"
    accepted, errors = extract_facts({"id": "s", "pages": [TABLE]}, [row])
    assert not accepted and any("context quote not found" in e for e in errors)


def test_equal_table_values_in_different_periods_keep_distinct_ids():
    a, b = table_fact(), table_fact()
    b["fiscal_period"] = "FY2024"
    rows, errors = extract_facts({"id": "s", "pages": [TABLE]}, [a, b])
    assert not errors and len({r["id"] for r in rows}) == 2


def test_table_context_does_not_validate_a_number_missing_from_row():
    row = table_fact()
    row["value"] = "2025"
    accepted, errors = extract_facts({"id": "s", "pages": [TABLE]}, [row])
    assert not accepted and "numeric value not in quote" in errors


def test_yearless_fact_not_grounded_by_unrelated_document_text():
    row = table_fact()
    row["context_evidence"] = []
    accepted, errors = extract_facts({"id": "s", "pages": [TABLE]}, [row])
    assert not accepted and any("fiscal period year" in e for e in errors)


def test_falsification_cannot_target_past_window():
    test = {"metric": "Revenue growth (%)", "threshold": "0", "comparison": "above", "source": "Quarterly results",
            "window_start": "2026-07-01", "window_end": "2026-08-01"}
    with pytest.raises(ValueError, match="future"):
        validate_future_test(test, "2026-10-23")
    test.update(window_start="2026-10-24", window_end="2027-04-30")
    assert "proposed future test" in validate_future_test(test, "2026-10-23")


def test_scheduling_only_evidence_never_becomes_hypothesis(tmp_path):
    notice = "Earnings conference call scheduled for 31 July 2026 at 06:30 pm IST."
    class ScheduleWeb(FakeWeb):
        def collect(self, store, company, result, **kwargs):
            from pharma_scope.ingest import ingest
            path = store.root / 'schedule.txt'
            path.write_text(ISSUER.splitlines()[0] + '\n' + notice, encoding='utf-8')
            return ingest(store, path, company, 'Call schedule', 'Issuer', '', result['url'])
    class ScheduleOnly(FakeModel):
        def generate(self, task, schema, data, **kwargs):
            if schema in [schemas.HYPOTHESES, schemas.SKEPTIC, schemas.FINDINGS, schemas.CLAIM_AUDIT]:
                raise AssertionError("Scheduling-only facts must stop before hypothesis generation")
            result = super().generate(task, schema, data, **kwargs)
            if schema == schemas.FACTS:
                result["facts"] = [fact(notice)]
                result["geography_observations"] = []
            return result
    with_store = Store(tmp_path / "data")
    try:
        run = ResearchAgent(with_store, ScheduleOnly(), ScheduleWeb(), Limits(seconds=120)).run("EXAMPLE")
        assert run["status"] == "insufficient_evidence" and not run["findings"]
        assert run['facts']
        assert any("Insufficient financial evidence" in w for w in run["warnings"])
    finally:
        with_store.close()


def test_failed_calculations_do_not_leave_publishable_hypothesis(tmp_path):
    class BadCalc(FakeModel):
        def generate(self, task, schema, data, **kwargs):
            result = super().generate(task, schema, data, **kwargs)
            if schema == schemas.HYPOTHESES:
                result["hypotheses"][0]["calculations"][0]["inputs"] = []
            return result
    store = Store(tmp_path / "data")
    try:
        run = ResearchAgent(store, BadCalc(), FakeWeb(), Limits(seconds=120)).run("EXAMPLE")
        assert not run["hypotheses"] and not run["findings"]
    finally:
        store.close()


def test_claim_audit_withholds_unsupported_trading_relationship(tmp_path):
    class TradingClaim(FakeModel):
        def generate(self, task, schema, data, **kwargs):
            result = super().generate(task, schema, data, **kwargs)
            if schema == schemas.FINDINGS:
                result["findings"][0]["discovery"]["text"] = "Evening calls correlate with institutional trading volatility."
            if schema == schemas.CLAIM_AUDIT:
                result["reviews"][0].update(all_claims_supported=False, track_relevant=False,
                    unsupported_claims=["No price, volume or institutional-trading data supports this relationship."])
            return result
    store = Store(tmp_path / "data")
    try:
        run = ResearchAgent(store, TradingClaim(), FakeWeb(), Limits(seconds=120)).run("EXAMPLE")
        assert not run["findings"]
        assert any("claim-support audit failed" in w for w in run["warnings"])
    finally:
        store.close()


def test_financial_timeline_uses_fiscal_labels_without_inventing_days(tmp_path):
    class FiscalTimeline(FakeModel):
        def generate(self, task, schema, data, **kwargs):
            result = super().generate(task, schema, data, **kwargs)
            if schema == schemas.FINDINGS:
                financial = sorted([f for f in data['facts'] if f['value']], key=lambda f: f['fiscal_period'])
                result['findings'][0]['timeline'] = [{'date': 'FY' + f['fiscal_period'], 'description': 'Reported US revenue', 'evidence': [f['id']]} for f in financial]
            return result
    store = Store(tmp_path / 'data')
    try:
        run = ResearchAgent(store, FiscalTimeline(), FakeWeb(), Limits(seconds=120)).run('EXAMPLE')
        assert [p['date'] for p in run['findings'][0]['timeline']] == ['FY2021', 'FY2025']
    finally:
        store.close()


def test_extraction_reserves_analysis_time_and_keeps_unprocessed_sources(tmp_path):
    store = Store(tmp_path / 'data')
    try:
        model = FakeModel()
        run = ResearchAgent(store, model, FakeWeb(), Limits(seconds=120)).run('EXAMPLE')
        state = store.agent_state(run['id'])
        state['extracted'] = []
        agent = ResearchAgent(store, model, FakeWeb(), Limits(seconds=120))
        agent.remaining = lambda s: 1
        calls_before = len(model.calls)
        assert agent.extract(state) == 'skeptic'
        assert len(model.calls) == calls_before and not state['extracted']
        assert any('reserve budget' in w for w in state['warnings'])
    finally:
        store.close()


def test_failed_source_attempts_cannot_consume_opposing_evidence_reserve(tmp_path):
    import time
    class Failing(FakeWeb):
        def collect(self, *a, **kw):
            raise ValueError('Unavailable')
    store = Store(tmp_path / 'data')
    try:
        agent = ResearchAgent(store, FakeModel(), Failing(), Limits(seconds=120, sources=8))
        agent.started = time.monotonic()
        state = {'id': 'budget-test', 'events': [], 'warnings': [], 'attempted_urls': [], 'source_ids': [],
                 'usage': {'sources': 4}, 'company': 'EXAMPLE'}
        agent.collect(state, [{'url': f'https://example.test/{i}'} for i in range(10)], limit=2, budget_reserve=3)
        assert state['usage']['sources'] == 5  # three attempts remain available to opposing research
    finally:
        store.close()


def test_legacy_console_encoding_does_not_fail_a_saved_report(tmp_path):
    import os, subprocess, sys
    from pharma_scope.demo import seed_demo
    store = Store(tmp_path / 'data')
    try:
        run = seed_demo(store)
        run['warnings'].append('Revenue is measured in \u20b9.')
        store.save_run(run)
    finally:
        store.close()
    env = os.environ.copy()
    env['PYTHONIOENCODING'] = 'cp1252'
    result = subprocess.run([sys.executable, '-m', 'pharma_scope', '--data-dir', str(tmp_path / 'data'), 'show', run['id']],
                            capture_output=True, env=env)
    assert result.returncode == 0, result.stderr
    assert b'\\u20b9' in result.stdout


def test_partial_extraction_repairs_bad_numbers_without_losing_good_facts(tmp_path):
    class Partial(FakeModel):
        damaged = False
        def generate(self, task, schema, data, **kwargs):
            result = super().generate(task, schema, data, **kwargs)
            if schema == schemas.FACTS and any(r["value"] for r in result["facts"]) and not self.damaged:
                self.damaged = True
                for row in result["facts"]:
                    if row["value"]:
                        row["quote"] = "Unanchored financial number 999"
            return result
    store = Store(tmp_path / "data")
    try:
        run = ResearchAgent(store, Partial(), FakeWeb(), Limits(seconds=120)).run("EXAMPLE")
        assert len(run["facts"]) == 5
        assert len([f for f in run["facts"] if f["value"]]) == 2
    finally:
        store.close()


def test_official_index_follows_navigation_and_linked_cdn_pdfs(tmp_path):
    page = tmp_path / "index.html"
    page.write_text('<a href="/investors/financial-results">Financial Results</a>'
                    '<a href="https://cdn.example/2025/results.pdf">Annual results</a>'
                    '<a href="https://external.example/news">Financial results news</a>')
    class Metadata:
        def metadata(self, sid):
            return {"original_archive": str(page)}
    leads = WebTools().report_links(Metadata(), [{"id": "s", "url": "https://issuer.example/investors", "title": "Investor"}], "issuer.example")
    assert {r["url"] for r in leads} == {"https://issuer.example/investors/financial-results", "https://cdn.example/2025/results.pdf"}
    assert all(r['linked_from'] == 'https://issuer.example/investors' for r in leads)
    assert disclosure_score({"url": "https://issuer.example/results.pdf", "title": "Financial results"}) > disclosure_score({"url": "https://issuer.example/call.pdf", "title": "Earnings call intimation"})
