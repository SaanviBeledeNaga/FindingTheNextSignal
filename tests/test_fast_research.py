"""Concurrency and deadline checks retain the real evidence admission rules."""
import json
import subprocess
import threading
from types import SimpleNamespace

from pharma_scope import schemas
from pharma_scope.agent import Limits, ResearchAgent
from pharma_scope.store import Store
from pharma_scope.web_worker import supervise
from test_agent import FakeModel, FakeWeb


def test_parallel_extraction_keeps_checks_and_independent_review(tmp_path):
    barrier = threading.Barrier(2)

    class ConcurrentModel(FakeModel):
        def generate(self, task, schema, data, **kwargs):
            if schema == schemas.FACTS and 'previous_output' not in data:
                # Serial extraction cannot cross this barrier. Both documents must run.
                barrier.wait(timeout=5)
                response = super().generate(task, schema, data, **kwargs)
                if 'fda.gov' not in data['url']:
                    invented = dict(response['facts'][0], quote='Invented revenue is 99999.', value='99999')
                    response['facts'].append(invented)
                return response
            return super().generate(task, schema, data, **kwargs)

    with_store = Store(tmp_path / 'data')
    model = ConcurrentModel()
    try:
        run = ResearchAgent(with_store, model, FakeWeb(), Limits(fast_mode=True, rounds=1)).run('EXAMPLE')
        assert len(run['facts']) == 5
        assert all(f['value'] != '99999' for f in run['facts'])
        assert any('rejected fact' in w for w in run['warnings'])
        assert run['findings'][0]['status'] == 'unresolved'
        assert run['findings'][0]['calculations'][0]['result'] == '-10.000000'
        assert any('Independently challenge' in call for call in model.calls)
        assert any('Audit EACH draft' in call for call in model.calls)
        assert run['usage']['model_calls'] == 8
    finally:
        with_store.close()


def test_parallel_downloads_commit_only_on_sqlite_owner_thread(tmp_path):
    owner = threading.get_ident()
    barrier = threading.Barrier(2)

    class ParallelWeb(FakeWeb):
        def download(self, url, timeout):
            assert threading.get_ident() != owner
            barrier.wait(timeout=5)
            return {'url': url}

        def collect_downloaded(self, store, company, result, downloaded, **kwargs):
            assert threading.get_ident() == owner
            assert result['url'] == downloaded['url']
            return self.collect(store, company, result)

    store = Store(tmp_path / 'data')
    try:
        run = ResearchAgent(store, FakeModel(), ParallelWeb(), Limits(fast_mode=True, rounds=1)).run('EXAMPLE')
        assert len(run['sources']) == 2
        assert len(run['facts']) == 5
    finally:
        store.close()


def test_whole_worker_timeout_keeps_checkpoint_without_promoting_claim(tmp_path, monkeypatch):
    store = Store(tmp_path / 'data')
    run = ResearchAgent(store, FakeModel(), FakeWeb(), Limits()).run('EXAMPLE')
    store.close()
    path = tmp_path / 'job-test.json'
    job = {'id': 'job-test', 'run_id': run['id'], 'limits': {'seconds': 270}, 'status': 'running'}
    path.write_text(json.dumps(job), encoding='utf-8')
    killed = []

    class StalledProcess:
        def wait(self, timeout=None):
            if timeout is not None:
                assert timeout == 280
                raise subprocess.TimeoutExpired('research', timeout)
            return 0

        def kill(self):
            killed.append(True)

    monkeypatch.setattr('pharma_scope.web_worker.subprocess.Popen', lambda *a, **k: StalledProcess())
    supervise(path, job, SimpleNamespace(data_dir=str(tmp_path / 'data'), job='job-test'))
    saved = json.loads(path.read_text(encoding='utf-8'))
    assert killed and saved['status'] == 'finished'
    assert saved['result_status'] == 'budget_exhausted'
    store = Store(tmp_path / 'data')
    try:
        assert store.agent_state(run['id'])['status'] == 'budget_exhausted'
        assert store.run(run['id'])['findings'][0]['status'] == 'unresolved'
        assert (store.root / 'exports' / (run['id'] + '.html')).is_file()
    finally:
        store.close()


def test_bounded_pdf_parser_preserves_physical_pages_and_reuses_exact_bytes(tmp_path, monkeypatch):
    import pymupdf
    from pharma_scope.ingest import ingest
    path = tmp_path / 'disclosure.pdf'
    with pymupdf.open() as doc:
        for text in ['Example Pharma Limited annual report',
                     'Consolidated statement of profit and loss\nFY2024 FY2025\nRevenue 100 120 INR crore']:
            page = doc.new_page()
            page.insert_text((50,50),text)
        doc.save(path)
    store = Store(tmp_path / 'data')
    try:
        sid = ingest(store,path,'EXAMPLE','Test disclosure','Example Pharma','2025-06-01',parse_timeout=12)
        source = next(s for s in store.sources() if s['id']==sid)
        assert len(source['pages']) == 2
        assert 'Revenue 100 120 INR crore' in source['pages'][1]
        monkeypatch.setattr('pharma_scope.ingest.read_pages',lambda *a,**k: (_ for _ in ()).throw(AssertionError('Identical bytes must reuse text')))
        alias_sid = ingest(store,path,'EXAMPLE ALIAS','Test disclosure','Example Pharma','2025-06-01')
        alias = next(s for s in store.sources() if s['id']==alias_sid)
        assert alias['pages'] == source['pages']
        assert alias['sha256'] == source['sha256']
    finally:
        store.close()
