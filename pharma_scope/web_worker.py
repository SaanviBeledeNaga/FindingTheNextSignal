"""Background investigation owned by the browser dashboard; keys stay in Python."""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from .agent import ResearchAgent, Limits, ResearchPaused, BudgetExceeded
from .config import load_env
from .report import export
from .store import Store, now
from .evidence import IdentityResolutionError
from .web import IDENTIFIER, write_job


def supervise(path, job, args):
    """Bound the whole worker, including PDF parsing and unexpected provider stalls."""
    command = [sys.executable, '-m', 'pharma_scope.web_worker', '--data-dir', args.data_dir,
               '--job', args.job, '--execute']
    process = subprocess.Popen(command, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        process.wait(timeout=280)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        job = json.loads(path.read_text(encoding='utf-8'))
        store = Store(args.data_dir)
        try:
            state = store.agent_state(job['run_id'])
            state['status'] = 'budget_exhausted'
            state['elapsed'] = max(state.get('elapsed', 0), job['limits']['seconds'])
            state['warnings'].append('Bounded 270s cycle stopped at its 280s supervision deadline. Unreviewed claims are not a completed discovery.')
            store.checkpoint(state)
            run = ResearchAgent(store, model=object(), web=object()).snapshot(state)
            store.save_run(run)
            export(store, run, store.root / 'exports' / (run['id'] + '.html'))
        except (ValueError, OSError):
            pass
        finally:
            store.close()
        job.update(status='finished', result_status='budget_exhausted', finished=now(), updated=now(),
                   error='Cycle time limit reached. Saved evidence is available; unsupported conclusions remain withheld.')
        write_job(path, job)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', required=True)
    parser.add_argument('--job', required=True)
    parser.add_argument('--execute', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not IDENTIFIER.fullmatch(args.job) or not args.job.startswith('job-'):
        raise ValueError('Invalid job ID.')
    path = Path(args.data_dir).resolve() / 'jobs' / (args.job + '.json')
    job = json.loads(path.read_text(encoding='utf-8'))
    if job['limits'].get('fast_mode') and not args.execute:
        supervise(path, job, args)
        return
    job.update(status='running', started=now(), updated=now())
    write_job(path, job)
    load_env()
    store = Store(args.data_dir)
    try:
        agent = ResearchAgent(store, limits=Limits(**job['limits']))
        agent.cancel = lambda: path.with_suffix('.pause').exists()
        def progress(event):
            job.update(updated=now(), last_stage=event['stage'])
            write_job(path, job)
        agent.emit = progress
        run = agent.run(job['company'], resume=job['resume'], run_id=None if job['resume'] else job['run_id'])
        export(store, run, store.root / 'exports' / (run['id'] + '.html'))
        job.update(status='finished', result_status=run['status'], finished=now())
    except Exception as exc:
        job.update(status='paused' if isinstance(exc, ResearchPaused) else 'failed', finished=now(), error=f'Research stopped ({type(exc).__name__}). Saved evidence is retained; review the activity and continue research.')
        if isinstance(exc, IdentityResolutionError):
            job['error'] = 'Company identity needs verification: ' + str(exc) + ' The checkpoint is saved.'
        if isinstance(exc, BudgetExceeded):
            job.update(status='finished', result_status='budget_exhausted',
                       error='Research cycle finished at its limit. Review the saved evidence and remaining gaps.')
        try:
            run = store.run(job['run_id'])
            export(store, run, store.root / 'exports' / (run['id'] + '.html'))
        except (ValueError, OSError):
            pass
    finally:
        store.close()
        write_job(path, job)


if __name__ == '__main__':
    main()
