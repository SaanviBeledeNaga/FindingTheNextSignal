"""Dated official constituent snapshot; never a claim of live/historical membership."""
import csv
import io
import json
from pathlib import Path
import re

from .store import digest, now

SNAPSHOT = Path(__file__).with_name('data') / 'nifty50.json'
SOURCE = 'https://nsearchives.nseindia.com/content/indices/ind_nifty50list.csv'


def key(value):
    return ''.join(w for w in re.findall(r'[a-z0-9]+',str(value).lower()) if w not in {'ltd','limited','inc','incorporated'})


def check(profile, path=SNAPSHOT):
    try:
        snapshot = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError,ValueError):
        return {'status':'unknown','member':None,'track_d':None,'detail':'Constituent snapshot unavailable.'}
    name = key(profile.get('name',''))
    symbol = str(profile.get('symbol','')).upper().strip()
    members = snapshot['members']
    match = next((r for r in members if key(r['Company Name']) == name or key(r['Symbol']) == name),None)
    if not match and symbol:
        candidate = next((r for r in members if r['Symbol']==symbol),None)
        if candidate and len(name)>=6 and (key(candidate['Company Name']).startswith(name) or name.startswith(key(candidate['Company Name']))):
            match = candidate
    result = {'snapshot_retrieved_at':snapshot['retrieved_at'],'source_url':snapshot['source_url'],
              'source_sha256':snapshot['sha256'],'effective_date':snapshot.get('effective_date'),
              'membership_basis':'Static downloaded snapshot; live and historical membership are not established.'}
    if not match:
        return {**result,'status':'not_in_snapshot','member':False,'track_d':None,
                'detail':'Not matched in the NIFTY 50 snapshot. Extended-universe research is allowed; sector eligibility is unverified.'}
    track = match['Industry'].casefold() in {'healthcare','pharmaceuticals','pharma & healthcare'}
    return {**result,'status':'track_d_member' if track else 'outside_track','member':True,'track_d':track,
            'company':match['Company Name'],'symbol':match['Symbol'],'industry':match['Industry'],
            'detail':'NIFTY 50 / Track D in the downloaded snapshot.' if track else 'NIFTY 50 member in the snapshot, outside Track D industry classification.'}


def refresh(path=SNAPSHOT):
    import httpx
    response=httpx.get(SOURCE,timeout=20,follow_redirects=False)
    response.raise_for_status()
    rows=list(csv.DictReader(io.StringIO(response.text.lstrip('\ufeff'))))
    if len(rows)!=50 or any(not {'Company Name','Symbol','Industry'} <= r.keys() for r in rows) or len({r['Symbol'] for r in rows})!=50:
        raise ValueError('Official response is not a complete unique 50-company constituent CSV; existing snapshot retained.')
    value={'index':'NIFTY 50','source_url':SOURCE,'retrieved_at':now(),'effective_date':None,
           'sha256':digest(response.content),'members':rows}
    Path(path).write_text(json.dumps(value,indent=2),encoding='utf-8')
    return value
