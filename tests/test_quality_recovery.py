"""A rejected model response must not silently become the final product."""
import pytest

from pharma_scope import schemas
from pharma_scope.agent import ResearchAgent, Limits
from pharma_scope.evidence import calculation, origin, validate_finding
from pharma_scope.quality import readiness
from pharma_scope.store import Store
from test_agent import FakeModel, FakeWeb


@pytest.fixture
def store(tmp_path):
    with_store = Store(tmp_path / 'data')
    yield with_store
    with_store.close()


def test_invalid_review_receives_bounded_repair(store):
    class BrokenReview(FakeModel):
        broken = False
        def generate(self, task, schema, data, **kwargs):
            result = super().generate(task, schema, data, **kwargs)
            if schema == schemas.SKEPTIC and not self.broken:
                self.broken = True
                result['reviews'][0]['supporting_facts'] = ['invented-fact']
            return result
    model = BrokenReview()
    run = ResearchAgent(store, model, FakeWeb(), Limits(seconds=120)).run('EXAMPLE')
    assert run['reviews'] and run['findings']
    assert any('Repair the missing skeptic' in task for task in model.calls)
    assert all(f['status'] != 'supported' for f in run['findings'])


def test_invalid_calculation_receives_grounded_repair(store):
    class BrokenCalculation(FakeModel):
        broken = False
        def generate(self, task, schema, data, **kwargs):
            result = super().generate(task, schema, data, **kwargs)
            if schema == schemas.HYPOTHESES and not self.broken:
                self.broken = True
                assert data['validated_calculation_candidates']
                result['hypotheses'][0]['calculations'][0]['inputs'] = ['missing', 'fact']
            return result
    model = BrokenCalculation()
    run = ResearchAgent(store, model, FakeWeb(), Limits(seconds=120)).run('EXAMPLE')
    assert run['calculations'] and run['hypotheses']
    assert any('Repair rejected hypotheses' in task for task in model.calls)


def test_units_in_threshold_are_repaired_without_relaxing_validation(store):
    class ThresholdUnits(FakeModel):
        def generate(self, task, schema, data, **kwargs):
            result = super().generate(task, schema, data, **kwargs)
            if schema == schemas.SKEPTIC:
                if 'validation_errors' not in data:
                    result['reviews'][0]['future_test']['threshold'] = '5000 Million INR'
                else:
                    assert any('finite number' in error for error in data['validation_errors'])
                    assert 'DECIMAL TEXT ONLY' in task
            return result
    run = ResearchAgent(store, ThresholdUnits(), FakeWeb(), Limits(seconds=120)).run('EXAMPLE')
    assert run['reviews'] and run['findings']
    assert run['reviews'][0]['future_test']['threshold'] == '0'


def test_resume_insufficient_reopens_research_without_discarding_facts(store):
    model = FakeModel()
    first = ResearchAgent(store, model, FakeWeb(), Limits(seconds=120)).run('EXAMPLE')
    before = {f['id'] for f in first['facts']}
    resumed = ResearchAgent(store, model, FakeWeb(), Limits(seconds=240)).run(resume=first['id'])
    assert before <= {f['id'] for f in resumed['facts']}
    assert sum(e['stage'] == 'resume' for e in resumed['events']) == 1
    assert len(resumed['events']) > len(first['events'])
    assert resumed['status'] == 'insufficient_evidence'


def test_growth_does_not_mix_first_and_fourth_quarter(store):
    run = ResearchAgent(store, FakeModel(), FakeWeb(), Limits(seconds=120)).run('EXAMPLE')
    rows = [dict(f) for f in run['facts'] if f['value']]
    rows[0]['fiscal_period'], rows[1]['fiscal_period'] = 'FY2024-Q1', 'FY2025-Q4'
    with pytest.raises(ValueError, match='comparable'):
        calculation({'operation': 'growth_pct', 'inputs': ['a', 'b'], 'years': 1}, dict(zip(['a', 'b'], rows)))


def test_lookalike_regulator_domain_is_not_verified():
    assert origin({'url': 'https://fakefda.gov.example.com/doc', 'publisher': '', 'source_kind': 'regulator'}, {}).startswith('unverified:')
    assert origin({'url': 'https://evilfda.gov/doc', 'publisher': '', 'source_kind': 'regulator'}, {}).startswith('regulator:')  # .gov namespace


def test_readiness_never_calls_unresolved_report_complete(store):
    run = ResearchAgent(store, FakeModel(), FakeWeb(), Limits(seconds=120)).run('EXAMPLE')
    assert not next(c for c in readiness(run) if c['name'] == 'Supported Discovery')['passed']
    from pharma_scope.research_report import html
    report = html(run)
    assert 'Research Incomplete' in report and 'not a guarantee of accuracy' in report


def test_calculation_requires_actual_input_citations(store):
    run = ResearchAgent(store, FakeModel(), FakeWeb(), Limits(seconds=120)).run('EXAMPLE')
    draft = FakeModel().generate('', schemas.FINDINGS, {'facts': run['facts']})['findings'][0]
    draft['discovery']['evidence'] = [next(f['id'] for f in run['facts'] if f['kind'] == 'regulatory')]
    with pytest.raises(ValueError, match='actual input facts'):
        validate_finding(draft, run['reviews'][0], run['hypotheses'][0],
                         {f['id']: f for f in run['facts']}, {s['id']: s for s in run['sources']},
                         run['calculations'], run['profile'], run['as_of'])


def test_followup_queries_keep_company_scope(store):
    class QueryWeb(FakeWeb):
        queries = []
        def search(self, query, **kwargs):
            self.queries.append(query)
            return super().search(query, **kwargs)
    web = QueryWeb()
    ResearchAgent(store, FakeModel(), web, Limits(seconds=120)).run('EXAMPLE')
    assert any(q.startswith('Example Pharma Limited ') and 'constant currency' in q for q in web.queries)


def test_government_numbers_are_not_target_company_financial_inputs():
    from pharma_scope.evidence import company_financial_facts
    rows = [{'kind': 'financial', 'value': '381.9', 'entity': 'United States Government'},
            {'kind': 'financial', 'value': '525', 'entity': 'Example Pharma'},
            {'kind': 'financial', 'value': '10', 'entity': 'Known Subsidiary Limited'}]
    kept, errors = company_financial_facts(rows, {'name': 'Example Pharma Limited', 'subsidiaries': ['Known Subsidiary']})
    assert len(kept) == 2 and len(errors) == 1
    assert 'United States Government' in errors[0]


def test_resume_rechecks_findings_that_used_out_of_scope_inputs(store):
    first = ResearchAgent(store, FakeModel(), FakeWeb(), Limits(seconds=120)).run('EXAMPLE')
    state = store.agent_state(first['id'])
    outside = {**next(f for f in state['facts'] if f['value']), 'id': 'government-number', 'entity': 'United States Government'}
    state['facts'].append(outside)
    state['calculations']['us-growth']['inputs'][0] = outside['id']
    state['status'] = 'completed'
    store.checkpoint(state)
    run = ResearchAgent(store, FakeModel(), FakeWeb(), Limits(seconds=240)).run(resume=first['id'])
    assert outside['id'] not in {f['id'] for f in run['facts']}
    assert run['status'] == 'insufficient_evidence'
    assert any('require fresh review' in warning for warning in run['warnings'])
