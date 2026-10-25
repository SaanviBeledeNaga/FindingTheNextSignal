"""Real HTTP requests and background-worker execution with fake research providers."""
from dataclasses import asdict
import json
from pathlib import Path
import threading
import time

import httpx
import pytest

from pharma_scope.agent import Limits, ResearchAgent
from pharma_scope.store import Store
from pharma_scope.web import DashboardServer, browser_run, write_job, snapshot
from test_agent import FakeModel, FakeWeb


@pytest.fixture
def dashboard(tmp_path):
    root = tmp_path / 'data'
    store = Store(root)
    run = ResearchAgent(store, FakeModel(), FakeWeb(), Limits(seconds=120)).run('EXAMPLE')
    store.close()
    server = DashboardServer(root, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = httpx.Client(base_url=f'http://127.0.0.1:{server.server_port}', trust_env=False)
    yield server, client, run
    client.close()
    server.shutdown()
    server.server_close()
    thread.join(5)


def test_dashboard_reads_real_saved_research_and_serves_assets(dashboard):
    server, client, original = dashboard
    for path, mime in [('/', 'text/html'), ('/app.js', 'text/javascript'), ('/style.css', 'text/css')]:
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers['content-type'].startswith(mime)
        assert 'frame-ancestors' in response.headers['content-security-policy']
    run = client.get('/api/run', params={'id': original['id']}).json()
    assert run['id'] == original['id']
    assert len(run['facts']) == 5
    assert len(run['completion_checks']) == 5
    assert not run['completion_checks'][-1]['passed']
    assert all('pages' not in source and 'archived' not in source for source in run['sources'])
    assert client.get('/api/runs').json()['runs'][0]['id'] == run['id']
    assert client.get('/audit.json').json()['overall'].startswith('Partial')


def test_http_api_blocks_cross_site_writes_and_host_rebinding(dashboard):
    server, client, run = dashboard
    assert client.post('/api/research', json={'company': 'Example'}).status_code == 403
    token = client.get('/api/bootstrap').json()['token']
    assert client.post('/api/research', headers={'X-Pharma-Token': token, 'Origin': 'https://other.example'}, json={'company': 'Example'}).status_code == 403
    assert client.get('/api/bootstrap', headers={'Host': 'evil.example'}).status_code == 403
    assert client.get('/.env').status_code == 404
    assert client.get('/api/run', params={'id': '../../.env'}).status_code == 400


def test_exports_and_archive_challenge_use_actual_evidence(dashboard):
    server, client, run = dashboard
    token = client.get('/api/bootstrap').json()['token']
    result = client.post('/api/challenge', headers={'X-Pharma-Token': token}, json={'run': run['id'], 'finding': run['findings'][0]['id'], 'question': 'Could currency translation explain this?'}).json()
    assert result['status'] == 'unresolved' and result['matches']
    for fmt in ('html', 'md', 'json'):
        response = client.get('/api/export', params={'id': run['id'], 'format': fmt})
        assert response.status_code == 200
        assert 'attachment' in response.headers['content-disposition']
        assert 'Example' in response.text
    assert 'Research Incomplete' in client.get('/api/export', params={'id': run['id']}).text


def test_browser_snapshot_reads_latest_checkpoint(dashboard):
    server, client, run = dashboard
    store = Store(server.root)
    state = store.agent_state(run['id'])
    state['usage']['model_calls'] = 99
    store.checkpoint(state)
    store.close()
    assert client.get('/api/run', params={'id': run['id']}).json()['usage']['model_calls'] == 99


def test_research_start_validates_budget_and_runs_worker_without_live_apis(dashboard, monkeypatch):
    server, client, original = dashboard
    monkeypatch.setattr('pharma_scope.web.doctor', lambda: {'ready_for_live_research': True})
    class Process:
        def poll(self): return None
    calls = []
    monkeypatch.setattr('pharma_scope.web.subprocess.Popen', lambda args, **kw: calls.append(args) or Process())
    token = client.get('/api/bootstrap').json()['token']
    response = client.post('/api/research', headers={'X-Pharma-Token': token}, json={'company': 'EXAMPLE', 'depth': 'deep'})
    assert response.status_code == 202
    job = response.json()
    assert job['limits']['seconds'] == 270
    assert job['run_id'].startswith('run-')
    assert calls[0][1:3] == ['-m', 'pharma_scope.web_worker']
    assert client.post('/api/research', headers={'X-Pharma-Token': token}, json={'company': 'EXAMPLE'}).status_code == 400
    from pharma_scope import web_worker
    class FakeAgent(ResearchAgent):
        def __init__(self, store, limits):
            super().__init__(store, FakeModel(), FakeWeb(), limits)
    monkeypatch.setattr(web_worker, 'ResearchAgent', FakeAgent)
    monkeypatch.setattr('sys.argv', ['web_worker', '--data-dir', str(server.root), '--job', job['id'], '--execute'])
    web_worker.main()
    saved = json.loads((server.root/'jobs'/(job['id']+'.json')).read_text())
    assert saved['status'] == 'finished' and saved['result_status'] == 'insufficient_evidence'
    assert client.get('/api/run', params={'id': job['run_id']}).json()['facts']
    assert (server.root/'exports'/(job['run_id']+'.html')).exists()


def test_continuation_adds_budgets_to_actual_spent_usage(dashboard, monkeypatch):
    server, client, original = dashboard
    monkeypatch.setattr('pharma_scope.web.doctor', lambda: {'ready_for_live_research': True})
    class Process:
        def poll(self): return None
    monkeypatch.setattr('pharma_scope.web.subprocess.Popen', lambda *a, **kw: Process())
    job = server.jobs.start({'resume': original['id'], 'depth': 'standard'})
    assert job['run_id'] == original['id']
    assert job['limits']['model_calls'] == original['usage']['model_calls'] + 20
    assert job['limits']['sources'] == original['usage']['sources'] + 12


def test_settings_api_never_returns_key_values(dashboard, monkeypatch):
    server, client, run = dashboard
    monkeypatch.setenv('GEMINI_API_KEY', 'secret-test-value-not-for-browser')
    body = client.get('/api/bootstrap').text
    assert 'secret-test-value-not-for-browser' not in body


def test_web_is_the_only_interactive_cli():
    from pharma_scope.cli import parser
    assert parser().parse_args(['web', '--port', '8888']).command == 'web'
    with pytest.raises(SystemExit):
        parser().parse_args(['tui'])


def test_pause_is_cooperative_and_checkpointed(dashboard, monkeypatch):
    server, client, original = dashboard
    monkeypatch.setattr('pharma_scope.web.doctor', lambda: {'ready_for_live_research': True})
    class Process:
        def poll(self): return None
    monkeypatch.setattr('pharma_scope.web.subprocess.Popen', lambda *a, **kw: Process())
    job = server.jobs.start({'company':'EXAMPLE','depth':'standard'})
    token = client.get('/api/bootstrap').json()['token']
    assert client.post('/api/pause', headers={'X-Pharma-Token':token}, json={}).json()['pause_requested']
    from pharma_scope import web_worker
    class FakeAgent(ResearchAgent):
        def __init__(self, store, limits): super().__init__(store, FakeModel(), FakeWeb(), limits)
    monkeypatch.setattr(web_worker,'ResearchAgent',FakeAgent)
    monkeypatch.setattr('sys.argv',['web_worker','--data-dir',str(server.root),'--job',job['id'],'--execute'])
    web_worker.main()
    assert server.jobs.status()['status'] == 'paused'
    store = Store(server.root)
    try:
        assert store.agent_state(job['run_id'])['status'] == 'interrupted'
    finally:
        store.close()
