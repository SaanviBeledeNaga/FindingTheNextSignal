"""Reproducible live company evaluation using unchanged Wider-mode settings."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys
import time

from .agent import ResearchAgent
from .config import doctor, load_env
from .report import export
from .store import Store, now, uid
from .web import write_job

COMPANIES = ['Cipla', "Dr. Reddy's Laboratories", 'Sun Pharmaceutical Industries',
             'Lupin', 'Zydus Lifesciences', 'Apollo Hospitals Enterprise']


def run_one(root, company):
    job_id,run_id=uid('job'),uid('run')
    limits=dict(seconds=270,searches=10,sources=16,model_calls=24,rounds=1,
                hypotheses=2,pages_per_source=8,fast_mode=True)
    path=root/'jobs'/(job_id+'.json')
    write_job(path,dict(id=job_id,run_id=run_id,company=company,resume=None,limits=limits,
                       depth='deep',evaluation=True,status='queued',created=now(),error=None))
    started=time.monotonic()
    with path.with_suffix('.log').open('wb') as log:
        process=subprocess.Popen([sys.executable,'-m','pharma_scope.web_worker','--data-dir',str(root),'--job',job_id],stdout=log,stderr=log)
        process.wait()
    job=json.loads(path.read_text(encoding='utf-8'))
    record={'company':company,'run_id':run_id,'job_id':job_id,'elapsed_seconds':round(time.monotonic()-started,2),
            'job_status':job['status'],'error':job.get('error')}
    store=Store(root)
    try:
        state=store.agent_state(run_id)
        run=ResearchAgent(store,model=object(),web=object()).snapshot(state)
        export(store,run,root/'exports'/(run_id+'.html'))
        record.update(status=run['status'],sources=len(run['sources']),accepted_facts=len(run['facts']),
                      financial_inputs=sum(f['kind']=='financial' and bool(f['value']) for f in run['facts']),
                      calculations=len(run['calculations']),findings=len(run['findings']),
                      supported=sum(f['status']=='supported' for f in run['findings']),
                      unresolved=sum(f['status']=='unresolved' for f in run['findings']),
                      excluded=len(run.get('excluded_evidence',[])),eligibility=run.get('profile',{}).get('eligibility',{}),
                      warnings=run['warnings'],usage={k:v for k,v in run['usage'].items() if k!='model_usage'})
    except ValueError:
        record.update(status='failed',sources=0,accepted_facts=0,financial_inputs=0,calculations=0,findings=0,supported=0,unresolved=0)
    finally:
        store.close()
    return record


def demo_case(root, records, destination):
    store=Store(root)
    candidates=[]
    try:
        for record in records:
            try:
                run=ResearchAgent(store,model=object(),web=object()).snapshot(store.agent_state(record['run_id']))
            except ValueError:
                continue
            for finding in run['findings']:
                if finding['status'] in {'supported','unresolved'}:
                    score=(finding['status']=='supported',{'Strong':3,'Moderate':2,'Weak':1}.get(finding['strength'],0),len(finding['discovery_evidence']))
                    candidates.append((score,run,finding))
        if not candidates:
            destination.write_text('# Live evaluation case\n\nNo finding qualified as supported or unresolved under the current evidence policy. The evaluation summary records every attempted company and failure; no fictional result substitutes for it.\n',encoding='utf-8')
            return None
        _,run,finding=max(candidates,key=lambda row:row[0])
        facts={f['id']:f for f in run['facts']}; sources={s['id']:s for s in run['sources']}
        lines=['# Real company walkthrough',f"\nCompany: **{run['company']}**. Run: `{run['id']}`.",
               f"\nStatus: **{finding['status']}**. Evidence strength: **{finding['strength']}**.",
               '\nThis is an actual autonomous run. An unresolved result is a tested hypothesis, not a proven causal discovery.',
               '\n## Finding',finding['claim'],'\n## Why it matters']
        lines += ['- '+b['text'] for b in finding['why_it_matters']]
        lines += ['\n## Numbers']+[f"- {c['purpose']}: {c['result']} {c['unit']}; {c['formula']}; inputs {c['input_values']}; periods {c['input_periods']}." for c in finding['calculations']]
        lines += ['\n## Timeline']+[f"- {t['date']}: {t['description']}" for t in finding['timeline']]
        lines += ['\n## Evidence trail']
        all_ids=set(finding.get('evidence',[])+finding.get('opposing_evidence',[])+finding['discovery_evidence'])
        for fid in sorted(all_ids):
            fact=facts[fid]; source=sources[fact['source_id']]
            lines += [f"\n### {fid}",f"[{source['title']}]({source['url']}) — physical page {fact['page']}; published {source['published'] or 'unknown'}.",
                      '\n> '+fact['quote'].replace('\n','\n> ')]
            for anchor in fact.get('context_evidence',[]):
                lines += [f"\nContext, physical page {anchor['page']}:\n\n> "+anchor['quote'].replace('\n','\n> ')]
        lines += ['\n## Counterargument',*finding['counterarguments'],'\n## Falsification condition',finding['falsification'],
                  '\n## Evidence-strength reasoning',finding['strength_reason'],'\n## What was withheld or remains uncertain']
        lines += ['- '+w for w in run['warnings'] if 'withheld' in w.lower() or 'rejected fact' in w.lower()][:12]
        lines += ['- '+p for p in finding['limitations']]
        destination.write_text('\n\n'.join(lines)+'\n',encoding='utf-8')
        return {'run_id':run['id'],'company':run['company'],'finding_id':finding['id'],'status':finding['status'],'strength':finding['strength']}
    finally:
        store.close()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data-dir',default='.pharma');p.add_argument('--companies',nargs='+')
    p.add_argument('--extend',help='Existing evaluation directory name; append companies up to eight total')
    p.add_argument('--workers',type=int,choices=[1,2],default=2)
    args=p.parse_args();load_env()
    args.companies=args.companies or COMPANIES
    configuration=doctor()
    if not configuration['ready_for_live_research']:
        p.error('Configure the local model and search settings first.')
    root=Path(args.data_dir).resolve();(root/'jobs').mkdir(parents=True,exist_ok=True)
    if args.extend:
        destination=(root/'evaluations'/args.extend).resolve()
        if destination.parent != (root/'evaluations').resolve():
            p.error('Evaluation must be inside the local evaluations directory.')
        manifest=json.loads((destination/'results.json').read_text(encoding='utf-8'))
        if set(args.companies)&set(manifest['companies']):
            p.error('Extended company names must be new.')
        manifest['companies']+=args.companies
        manifest['revision_note']='After the first six trials, a general identity-token guard and comparable-pair extraction guidance were added. All cases retain the same Wider budgets; public evidence is revalidated under the current policy.'
    else:
        destination=root/'evaluations'/uid('evaluation');destination.mkdir(parents=True)
        manifest={'created':now(),'mode':'Wider / bounded 270s cycle','workers':args.workers,
                  'model':configuration['model'],'search':configuration['search_provider'],'companies':args.companies,'records':[]}
    if not 5<=len(manifest['companies'])<=8 or len(set(manifest['companies']))!=len(manifest['companies']):
        p.error('Choose 5–8 distinct companies in the complete evaluation.')
    print('Evaluation directory: '+str(destination),flush=True)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        pending={pool.submit(run_one,root,c):c for c in args.companies}
        for future in as_completed(pending):
            try: record=future.result()
            except Exception as exc: record={'company':pending[future],'status':'evaluation_error','error':type(exc).__name__}
            manifest['records'].append(record)
            (destination/'results.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
            print(json.dumps({k:record.get(k) for k in ['company','run_id','elapsed_seconds','status','financial_inputs','supported','unresolved']}),flush=True)
    # Revalidate earlier records as well: later policy fixes must not leave an
    # entity mismatch or excluded figures counted as successful evidence.
    store=Store(root)
    try:
        for record in manifest['records']:
            if 'run_id' not in record:continue
            run=ResearchAgent(store,model=object(),web=object()).snapshot(store.agent_state(record['run_id']))
            record.update(status=run['status'],accepted_facts=len(run['facts']),
                          financial_inputs=sum(f['kind']=='financial' and bool(f['value']) for f in run['facts']),
                          calculations=len(run['calculations']),findings=len(run['findings']),
                          supported=sum(f['status']=='supported' for f in run['findings']),
                          unresolved=sum(f['status']=='unresolved' for f in run['findings']),
                          warnings=run['warnings'],identity_mismatch=run.get('identity_mismatch',False),
                          withheld_findings=run.get('withheld_findings',[]))
            store.save_run(run)
            export(store,run,root/'exports'/(run['id']+'.html'))
    finally:store.close()
    manifest['demo']=demo_case(root,manifest['records'],destination/'real-case.md')
    manifest['finished']=now()
    (destination/'results.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    rows=['# Live company evaluation','',f"Created {manifest['created']}. Same Wider settings for all companies; no company-specific thesis or manual input data.",'',
          '| Company | Cycle seconds | Financial inputs | Supported | Unresolved | Status |','|---|---:|---:|---:|---:|---|']
    rows += [f"| {r['company']} | {r.get('elapsed_seconds','—')} | {r.get('financial_inputs',0)} | {r.get('supported',0)} | {r.get('unresolved',0)} | {r['status']} |" for r in manifest['records']]
    rows += ['', 'Best qualifying case: '+json.dumps(manifest['demo']) if manifest['demo'] else 'No demo-qualified finding. Failures are retained in results.json.']
    (destination/'summary.md').write_text('\n'.join(rows)+'\n',encoding='utf-8')
    print('Evaluation complete: '+str(destination),flush=True)


if __name__=='__main__':main()
