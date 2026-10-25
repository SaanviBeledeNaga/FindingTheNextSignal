import pytest
from pharma_scope.quality import scope_warning, scope_issues, readiness
from pharma_scope.agent import ResearchAgent, Limits
from pharma_scope.evidence import validate_finding
from pharma_scope.store import Store
from test_agent import FakeModel, FakeWeb
from pharma_scope import schemas


def test_mixed_scope_comparison_requires_explicit_scope_labels():
    facts = {'inventory': {'value': '30', 'basis': 'standalone'}, 'revenue': {'value': '20', 'basis': 'consolidated'}}
    assert scope_warning('Inventory grew faster than revenue.', facts, facts)
    assert not scope_warning('Standalone inventory grew faster than consolidated revenue; reporting scopes differ.', facts, facts)
    assert scope_warning('Consolidated inventory grew.', ['inventory'], facts)


def test_legacy_scope_conflict_is_visible_and_new_claim_is_rejected(tmp_path):
    store = Store(tmp_path/'data')
    try:
        run = ResearchAgent(store, FakeModel(), FakeWeb(), Limits(seconds=120)).run('EXAMPLE')
        numeric = [f for f in run['facts'] if f['value']]
        numeric[0]['basis'] = 'standalone'
        assert scope_issues(run)
        assert not next(c for c in readiness(run) if c['name'] == 'Reporting Scope')['passed']
        draft = FakeModel().generate('', schemas.FINDINGS, {'facts': run['facts']})['findings'][0]
        with pytest.raises(ValueError, match='reporting scope'):
            validate_finding(draft,run['reviews'][0],run['hypotheses'][0],{f['id']:f for f in run['facts']},
                             {s['id']:s for s in run['sources']},run['calculations'],run['profile'],run['as_of'])
    finally:
        store.close()
