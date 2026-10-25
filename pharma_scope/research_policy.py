"""Evidence admissibility shared by research, legacy display and exports."""
from copy import deepcopy
from datetime import date
from functools import lru_cache
from pathlib import Path
import re
from urllib.parse import urlparse

VERSION = 'evidence-4'
PREVIEW_HOSTS = {'scribd.com','slideshare.net','academia.edu'}


def compact(text):
    return re.sub(r'[^a-z0-9]','',str(text).lower())


def period_allowed(fact, as_of, years=5):
    if not fact.get('value') or fact.get('kind') != 'financial':
        return True
    match = re.fullmatch(r'(?:FY)?(20\d{2})(?:[- ]?Q[1-4])?',fact.get('fiscal_period',''),re.I)
    if not match:
        return False
    current = date.fromisoformat(as_of).year
    maximum = current + int('Q' in fact['fiscal_period'].upper())
    return current - years <= int(match[1]) <= maximum


def current_facts(facts, as_of, years=5):
    return [f for f in facts if period_allowed(f,as_of,years)]


@lru_cache(maxsize=64)
def company_mentioned(pages, names):
    # Cache by actual immutable text, never by a model-provided source ID or URL.
    text = compact(' '.join(pages))
    return any(name in text for name in names)


def source_issue(source, profile):
    host = (urlparse(source.get('url','')).hostname or '').lower()
    original = source.get('original_archive') or source.get('archived','')
    if not str(original).lower().endswith('.pdf') and any(host == d or host.endswith('.'+d) for d in PREVIEW_HOSTS):
        return 'Preview or upload-directory HTML is not the full underlying document.'
    names = [profile.get('name',''), *profile.get('aliases',[]), *profile.get('facilities',[])]
    names = [compact(re.sub(r'\b(limited|ltd|incorporated|inc)\b','',name,flags=re.I)) for name in names]
    names = [name for name in names if len(name) >= 6]
    if names and not company_mentioned(tuple(source.get('pages',[])), tuple(names)):
        return 'No grounded company or verified facility name in the document; not company-specific evidence.'
    return ''


def section_scope(source, page):
    pattern = re.compile(r'^\s*(?:notes\s+(?:to|forming part of)\s+)?(consolidated|standalone)\s+(?:financial\s+statements?|statements?\s+of\s+(?:profit|operations|income|cash|financial))\b',re.I)
    for index in range(page-1,max(-1,page-42),-1):
        matches = [(line,pattern.search(line)) for line in source['pages'][index].splitlines()]
        matches = [(line,m) for line,m in matches if m]
        if matches:
            scopes = {m[1].lower() for line,m in matches}
            if len(scopes) == 1:
                return {'page':index+1,'quote':matches[-1][0].strip(),'basis':next(iter(scopes))}
            return None
    return None


def finding_problems(finding, run):
    from .evidence import calculation, extract_facts
    from .quality import scope_warning
    facts = {f['id']:f for f in run.get('facts',[])}
    sources = {s['id']:s for s in run.get('sources',[])}
    problems = []
    cited = set(finding.get('discovery_evidence',[]))
    if len({facts[fid]['source_id'] for fid in cited if fid in facts}) < 2:
        problems.append('The discovery is not corroborated by at least two source documents.')
    if sum(bool(facts.get(fid,{}).get('value')) and facts.get(fid,{}).get('kind') == 'financial' for fid in cited) < 2:
        problems.append('The discovery does not cite two grounded financial measurements.')
    if not finding.get('calculations'):
        problems.append('No financial calculation substantiates the discovery.')
    for calc in finding.get('calculations',[]):
        try:
            if not set(calc['inputs']) <= cited:
                raise ValueError('Calculation inputs are not cited by the discovery.')
            recalculated = calculation(calc,facts)
            if str(recalculated['result']) != str(calc['result']):
                raise ValueError('Stored calculation result does not match its inputs.')
        except (ValueError,KeyError,ArithmeticError) as exc:
            problems.append(str(exc))
    for fid in cited:
        fact = facts.get(fid)
        if not fact or fact['source_id'] not in sources:
            problems.append('A cited fact or source is unavailable.')
            continue
        source = sources[fact['source_id']]
        if source_issue(source,run.get('profile',{})):
            problems.append(source_issue(source,run.get('profile',{})))
        if not period_allowed(fact,run.get('as_of',date.today().isoformat()),run.get('years',5)):
            problems.append('Financial evidence falls outside the requested research window.')
        if source.get('pages'):
            valid, errors = extract_facts(source,[fact])
            if not valid:
                problems.extend('Source validation: '+error for error in errors)
    warning = scope_warning(finding.get('claim',''),cited,facts)
    if warning:
        problems.append(warning)
    audit = finding.get('claim_audit',{})
    if not audit.get('all_claims_supported') or not audit.get('track_relevant') or audit.get('unsupported_claims'):
        problems.append('A passing claim-support audit is missing.')
    return list(dict.fromkeys(problems))


def publication_view(run):
    if run.get('demo') or run.get('kind') != 'research':
        return run
    result = deepcopy(run)
    from .evidence import identity_matches
    if result.get('profile') and not identity_matches(result['company'],result['profile']):
        result['warnings'] = [*result.get('warnings',[]),'Resolved entity does not match all distinctive words of the requested company; all interpretations withheld.']
        result.update(facts=[],findings=[],hypotheses=[],reviews=[],calculations={},status='failed')
        result['identity_mismatch'] = True
        return result
    accepted, withheld = [], list(result.get('withheld_findings',[]))
    for finding in result.get('findings',[]):
        problems = finding_problems(finding,result)
        if problems:
            withheld.append({'id':finding['id'],'claim':finding.get('claim',finding.get('title','')),'reasons':problems})
        else:
            accepted.append(finding)
    result['findings'] = accepted
    result['withheld_findings'] = list({f['id']:f for f in withheld}.values())
    sources = {s['id']:s for s in result.get('sources',[])}
    source_errors = {sid:source_issue(s,result.get('profile',{})) for sid,s in sources.items()}
    admitted, excluded = [], list(result.get('excluded_evidence',[]))
    from .evidence import extract_facts
    for fact in result.get('facts',[]):
        source = sources.get(fact['source_id'])
        error = source_errors.get(fact['source_id'],'Cited source missing.')
        if not period_allowed(fact,result.get('as_of',date.today().isoformat()),result.get('years',5)):
            error = 'Financial figure is outside the requested research window.'
        if not error and source and source.get('pages'):
            valid, errors = extract_facts(source,[fact])
            if not valid:
                error = '; '.join(errors)
        if error:
            excluded.append({'id':fact['id'],'reason':error})
        else:
            admitted.append(fact)
    result['facts'] = admitted
    admitted_ids = {f['id'] for f in admitted}
    result['calculations'] = {key:value for key,value in result.get('calculations',{}).items()
                              if set(value.get('inputs',[])) <= admitted_ids}
    result['hypotheses'] = [h for h in result.get('hypotheses',[])
                            if set(h.get('supporting_facts',[]) + h.get('opposing_facts',[])) <= admitted_ids]
    hypothesis_ids = {h['id'] for h in result['hypotheses']}
    result['reviews'] = [r for r in result.get('reviews',[]) if r.get('hypothesis_id') in hypothesis_ids]
    result['excluded_evidence'] = list({f['id']:f for f in excluded}.values())
    result['evidence_policy'] = VERSION
    if result.get('status') == 'completed' and not any(f['status']=='supported' for f in accepted):
        result['status'] = 'insufficient_evidence'
    return result
