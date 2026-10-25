"""Observable research completion checks; never a probability of factual truth."""
import re


def scope_warning(text, ids, facts):
    scopes = set()
    for fid in ids:
        fact = facts.get(fid, {})
        if fact.get('value'):
            basis = str(fact.get('basis', '')).lower()
            scopes.update(s for s in ('standalone', 'consolidated') if re.search(r'\b' + s + r'\b', basis))
    mentioned = {s for s in ('standalone', 'consolidated') if re.search(r'\b' + s + r'\b', text.lower())}
    if len(scopes) > 1 and not scopes <= mentioned:
        return 'Comparison combines standalone and consolidated financial inputs without distinguishing their reporting scope.'
    if len(scopes) == 1 and mentioned - scopes:
        return 'Text describes a reporting scope that contradicts its cited financial inputs.'
    return ''


def scope_issues(run):
    facts = {f['id']: f for f in run.get('facts', [])}
    issues = []
    for finding in run.get('findings', []):
        ids = set(finding.get('discovery_evidence', []))
        ids.update(fid for c in finding.get('calculations', []) for fid in c.get('inputs', []))
        warning = scope_warning(finding.get('claim', ''), ids, facts)
        if warning:
            issues.append(finding['id'] + ': ' + warning)
        for point in finding.get('timeline', []):
            warning = scope_warning(point['description'], point.get('evidence', []), facts)
            if warning:
                issues.append(finding['id'] + ': ' + warning)
    return list(dict.fromkeys(issues))


def readiness(run):
    findings = run.get('findings', [])
    hypotheses = run.get('hypotheses', [])
    reviews = {r['hypothesis_id'] for r in run.get('reviews', [])}
    numeric = sum(f.get('kind') == 'financial' and bool(f.get('value')) for f in run.get('facts', []))
    issues = scope_issues(run)
    checks = [
        ('Financial Inputs', numeric >= 2, f'{numeric} source-anchored financial numbers'),
        ('Comparable Calculations', bool(run.get('calculations')), f"{len(run.get('calculations', {}))} validated calculations"),
        ('Hypothesis Review', bool(hypotheses) and all(h['id'] in reviews for h in hypotheses),
         f'{len(reviews)} reviewed of {len(hypotheses)} retained hypotheses'),
        ('Reporting Scope', bool(run.get('facts')) and not issues, issues[0] if issues else 'No detected internal standalone/consolidated conflict; source interpretation still needs review'),
        ('Supported Discovery', not issues and any(f['status'] == 'supported' for f in findings),
         f"{sum(f['status'] == 'supported' for f in findings)} findings passed the support requirements"),
    ]
    return [{'name': name, 'passed': bool(passed), 'detail': detail} for name, passed, detail in checks]
