import json
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from pharma_scope import schemas
from pharma_scope.agent import Limits, ResearchAgent
from pharma_scope.providers import Model, TransientModelError
from pharma_scope.store import Store
from test_agent import FakeModel, FakeWeb


def configured_model(monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY', 'private-test-sentinel')
    return Model('gemini', 'test-model')


def test_stalled_worker_is_killed_at_wall_clock_deadline(monkeypatch):
    model = configured_model(monkeypatch)
    real_run = subprocess.run
    def stalled(*args, **kwargs):
        # Actual sleeping process: validates termination, rather than faking TimeoutExpired.
        return real_run([sys.executable, '-c', 'import time; time.sleep(30)'], **kwargs)
    monkeypatch.setattr(subprocess, 'run', stalled)
    started = time.monotonic()
    with pytest.raises(TransientModelError, match='wall-clock deadline'):
        model.generate_bounded('test', schemas.obj(value=schemas.S), {}, timeout=0.5)
    assert time.monotonic() - started < 5


def test_worker_result_preserves_usage_and_keeps_credentials_out_of_payload(monkeypatch):
    model = configured_model(monkeypatch)
    def completed(command, **kwargs):
        assert command[-1] == 'pharma_scope.model_worker'
        assert 'private-test-sentinel' not in kwargs['input']
        assert 'private-test-sentinel' not in ' '.join(command)
        assert kwargs['env']['GEMINI_API_KEY'] == 'private-test-sentinel'
        return SimpleNamespace(returncode=0, stdout=json.dumps({'result': {'value': 'grounded'}, 'usage': {'tokens': 4}}))
    monkeypatch.setattr(subprocess, 'run', completed)
    assert model.generate_bounded('test', schemas.obj(value=schemas.S), {}, timeout=5) == {'value': 'grounded'}
    assert model.last_usage == {'tokens': 4}


def test_worker_raw_stderr_is_not_exposed(monkeypatch):
    model = configured_model(monkeypatch)
    monkeypatch.setattr(subprocess, 'run', lambda *a, **kw: SimpleNamespace(returncode=1, stdout='', stderr='private-test-sentinel'))
    with pytest.raises(ValueError) as error:
        model.generate_bounded('test', schemas.obj(value=schemas.S), {}, timeout=5)
    assert 'private-test-sentinel' not in str(error.value)


def test_valid_facts_survive_a_repair_network_failure(tmp_path, monkeypatch):
    class RepairUnavailable(FakeModel):
        def generate(self, task, schema, data, **kwargs):
            if 'previous extraction failed' in task.lower():
                raise TransientModelError('Temporary repair failure')
            result = super().generate(task, schema, data, **kwargs)
            if schema == schemas.FACTS and any(f['value'] for f in result['facts']):
                result['facts'][0]['quote'] = 'Unanchored invented quote'
            return result
    monkeypatch.setattr('pharma_scope.agent.time.sleep', lambda duration: None)
    store = Store(tmp_path / 'data')
    try:
        with pytest.raises(TransientModelError):
            ResearchAgent(store, RepairUnavailable(), FakeWeb(), Limits(seconds=120)).run('EXAMPLE')
        saved = json.loads(store.db.execute('SELECT state FROM agent_states').fetchone()[0])
        assert len(saved['facts']) >= 2
        assert saved['next_stage'] == 'extract' and saved['status'] == 'failed'
    finally:
        store.close()


def test_cli_exports_partial_html_when_budget_is_exhausted(tmp_path, monkeypatch, capsys):
    from pharma_scope.cli import main
    monkeypatch.setattr('pharma_scope.config.load_env', lambda: None)
    monkeypatch.setattr('pharma_scope.providers.Model', lambda *a: FakeModel())
    monkeypatch.setattr('pharma_scope.agent.WebTools', FakeWeb)
    code = main(['--data-dir', str(tmp_path / 'data'), 'investigate', 'EXAMPLE', '--max-model-calls', '1'])
    assert code == 2
    paths = list((tmp_path / 'data/exports').glob('*.html'))
    assert len(paths) == 1
    assert 'budget exhausted' in paths[0].read_text(encoding='utf-8')
    assert 'Partial report (investigation incomplete)' in capsys.readouterr().err
