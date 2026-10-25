"""Loopback-only browser dashboard backed by the real research engine and archive."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from .agent import Limits, ResearchAgent
from .config import doctor
from .quality import readiness, scope_issues
from .store import Store, now, uid

ASSETS = Path(__file__).with_name('web_assets')
IDENTIFIER = re.compile(r'^(?:run|job)-[a-f0-9]{8,16}$')


def write_job(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value), encoding='utf-8')
    os.replace(temporary, path)


def snapshot(store, run_id):
    run = store.run(run_id)
    if run.get('kind') == 'research':
        try:
            state = store.agent_state(run['id'])
            run = ResearchAgent(store, model=object(), web=object()).snapshot(state)
        except ValueError:
            pass
    else:
        from .research_report import from_geography
        run = from_geography(run)
    return run


def browser_run(run):
    # Never send filesystem locations, raw downloaded files, or provider credentials.
    fields = ('id', 'company', 'created', 'status', 'demo', 'profile', 'parameters', 'as_of', 'withheld_findings', 'excluded_evidence',
              'usage', 'events', 'findings', 'warnings', 'facts', 'hypotheses', 'reviews', 'calculations')
    result = {key: run.get(key, [] if key in ('facts', 'findings', 'events', 'warnings', 'hypotheses', 'reviews', 'withheld_findings', 'excluded_evidence') else {}) for key in fields}
    result['sources'] = [{k: s.get(k, '') for k in ('id', 'title', 'publisher', 'published', 'url', 'sha256',
                         'original_sha256', 'retrieved_at', 'source_kind', 'origin_group')} for s in run.get('sources', [])]
    result['completion_checks'] = readiness(run)
    result['review_issues'] = scope_issues(run)
    result['usage'] = {k: v for k, v in run.get('usage', {}).items() if k != 'model_usage'}
    return result


class Jobs:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.directory = self.root / 'jobs'
        self.directory.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.process = None
        records = sorted(self.directory.glob('job-*.json'), key=lambda p:p.stat().st_mtime, reverse=True)
        self.current = records[0].stem if records else None

    def status(self):
        if self.current:
            path = self.directory / (self.current + '.json')
            job = json.loads(path.read_text(encoding='utf-8'))
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(job.get('updated', job['created']))).total_seconds()
            if job['status'] in ('queued', 'running') and ((self.process and self.process.poll() is not None) or (not self.process and age > 300)):
                job.update(status='failed', error='The research worker stopped. Saved checkpoints can be resumed.')
                write_job(path, job)
            job['pause_requested'] = (self.directory / (self.current + '.pause')).exists()
            return job
        return None

    def pause(self):
        job = self.status()
        if not job or job['status'] not in ('queued', 'running'):
            raise ValueError('There is no active investigation to pause.')
        (self.directory / (job['id'] + '.pause')).write_text('pause', encoding='utf-8')
        return self.status()

    def start(self, payload):
        with self.lock:
            existing = self.status()
            if existing and existing['status'] in ('queued', 'running'):
                raise ValueError('An investigation is already running. Follow its progress before starting another.')
            if not doctor()['ready_for_live_research']:
                raise ValueError('Model/search settings are incomplete. Configure the local .env file and restart the dashboard.')
            company = str(payload.get('company', '')).strip()
            resume = payload.get('resume')
            if resume and (not isinstance(resume, str) or not IDENTIFIER.fullmatch(resume) or not resume.startswith('run-')):
                raise ValueError('Choose a saved investigation to continue.')
            if not resume and (not 2 <= len(company) <= 160 or any(ord(c) < 32 for c in company)):
                raise ValueError('Enter a company name between 2 and 160 characters.')
            preset = payload.get('depth', 'deep')
            if preset not in ('standard', 'deep'):
                raise ValueError('Choose Standard or Deep research.')
            limits = dict(seconds=270, searches=8, sources=12, model_calls=20, rounds=1,
                          hypotheses=2, pages_per_source=6, fast_mode=True) if preset == 'standard' else dict(
                          seconds=270, searches=10, sources=16, model_calls=24, rounds=1,
                          hypotheses=2, pages_per_source=8, fast_mode=True)
            if resume:
                store = Store(self.root)
                try:
                    state = store.agent_state(resume)
                    if state.get('status') == 'completed':
                        raise ValueError('This investigation is complete. Start a fresh investigation to reassess it.')
                    company = state['company']
                    limits['seconds'] += int(state['elapsed']) + 1
                    for key in ('searches', 'sources', 'model_calls'):
                        limits[key] += state['usage'][key]
                finally:
                    store.close()
            Limits(**limits).validate()
            job_id = uid('job')
            job = dict(id=job_id, run_id=resume or uid('run'), company=company, resume=resume,
                       limits=limits, depth=preset, status='queued', created=now(), error=None)
            path = self.directory / (job_id + '.json')
            write_job(path, job)
            try:
                with (self.directory / (job_id + '.log')).open('wb') as log:
                    self.process = subprocess.Popen([sys.executable, '-m', 'pharma_scope.web_worker',
                        '--data-dir', str(self.root), '--job', job_id], stdout=log, stderr=log,
                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            except OSError:
                job.update(status='failed', error='Could not start the research worker.')
                write_job(path, job)
                raise ValueError(job['error']) from None
            self.current = job_id
            return job


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, root, port=8765):
        self.root = Path(root).resolve()
        self.token = secrets.token_urlsafe(32)
        self.jobs = Jobs(self.root)
        super().__init__(('127.0.0.1', port), DashboardHandler)


class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, status, body, mime='application/json; charset=utf-8', attachment=None):
        if not isinstance(body, bytes):
            body = json.dumps(body).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if attachment:
            self.send_header('Content-Disposition', f'attachment; filename="{attachment}"')
        self.end_headers()
        self.wfile.write(body)

    def valid_host(self):
        port = self.server.server_port
        return self.headers.get('Host') in (f'127.0.0.1:{port}', f'localhost:{port}')

    def do_GET(self):
        if not self.valid_host():
            return self.send(403, {'error': 'Use the localhost dashboard address.'})
        parsed = urlsplit(self.path)
        path, query = parsed.path, parse_qs(parsed.query)
        store = None
        try:
            if path in ('/', '/app.js', '/style.css', '/audit.json'):
                filename = {'/': 'index.html'}.get(path, path[1:])
                mime = {'html': 'text/html', 'js': 'text/javascript', 'css': 'text/css', 'json': 'application/json'}[filename.rsplit('.', 1)[-1]]
                return self.send(200, (ASSETS / filename).read_bytes(), mime + '; charset=utf-8')
            if path == '/api/bootstrap':
                return self.send(200, {'token': self.server.token, 'configuration': doctor(), 'job': self.server.jobs.status()})
            if path == '/api/job':
                return self.send(200, {'job': self.server.jobs.status()})
            store = Store(self.server.root)
            if path == '/api/runs':
                rows = store.db.execute('SELECT id,company,created,status FROM runs ORDER BY created DESC LIMIT 100').fetchall()
                return self.send(200, {'runs': [dict(r) for r in rows]})
            run_id = query.get('id', ['latest'])[0]
            if run_id != 'latest' and (not IDENTIFIER.fullmatch(run_id) or not run_id.startswith('run-')):
                raise ValueError('Invalid investigation ID.')
            if path == '/api/run':
                return self.send(200, browser_run(snapshot(store, run_id)))
            if path == '/api/export':
                from .research_report import html, markdown
                run = snapshot(store, run_id)
                fmt = query.get('format', ['html'])[0]
                if fmt == 'html':
                    return self.send(200, html(run, store.challenges(run['id'])).encode('utf-8'), 'text/html; charset=utf-8', run['id'] + '.html')
                if fmt == 'md':
                    return self.send(200, markdown(run).encode('utf-8'), 'text/markdown; charset=utf-8', run['id'] + '.md')
                if fmt == 'json':
                    return self.send(200, browser_run(run), attachment=run['id'] + '.json')
                raise ValueError('Choose HTML, Markdown or JSON.')
            return self.send(404, {'error': 'Page not found.'})
        except (ValueError, KeyError) as exc:
            self.send(400, {'error': str(exc)})
        except Exception:
            self.send(500, {'error': 'Could not read the local research archive.'})
        finally:
            if store:
                store.close()

    def do_POST(self):
        origin = self.headers.get('Origin')
        if (not self.valid_host() or self.headers.get('X-Pharma-Token') != self.server.token or
                (origin and origin not in (f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}'))):
            return self.send(403, {'error': 'Reload the local dashboard before making changes.'})
        store = None
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 10000:
                raise ValueError('Request is empty or too large.')
            if self.headers.get_content_type() != 'application/json':
                raise ValueError('Use a JSON request.')
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError('Expected a request object.')
            if self.path == '/api/research':
                return self.send(202, self.server.jobs.start(payload))
            if self.path == '/api/pause':
                return self.send(202, self.server.jobs.pause())
            if self.path == '/api/challenge':
                from .engine import challenge
                store = Store(self.server.root)
                question = str(payload.get('question', '')).strip()
                if not 2 <= len(question) <= 600:
                    raise ValueError('Enter a question between 2 and 600 characters.')
                result = challenge(store, str(payload.get('run', '')), str(payload.get('finding', '')), question)
                return self.send(200, result)
            return self.send(404, {'error': 'Action not found.'})
        except (ValueError, KeyError, TypeError) as exc:
            self.send(400, {'error': str(exc)})
        except Exception:
            self.send(500, {'error': 'The action could not finish. Saved research is retained.'})
        finally:
            if store:
                store.close()


def serve(root='.pharma', port=8765, open_browser=False):
    import webbrowser
    server = DashboardServer(root, port)
    url = f'http://127.0.0.1:{server.server_port}'
    print(f'PHARMA-SCOPE dashboard: {url}', flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            server.jobs.pause()
        except (ValueError, OSError):
            pass
        server.server_close()
