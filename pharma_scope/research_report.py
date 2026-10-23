"""Professional self-contained reports, with claim-level evidence anchors."""
from html import escape
import json
from urllib.parse import urlparse


def e(value):
    return escape(str(value), quote=True)


def safe_url(url):
    return url if urlparse(url).scheme in {"http", "https"} else ""


def references(ids):
    return " ".join(f'<a class="ref" href="#fact-{e(fid)}">[{e(fid)}]</a>' for fid in dict.fromkeys(ids))


def html(run, challenges=()):
    facts = {f["id"]: f for f in run["facts"]}
    sources = {s["id"]: s for s in run["sources"]}
    body = f'<header><p class="eyebrow">PHARMA-SCOPE · Track D</p><h1>{e(run.get("profile", {}).get("name", run["company"]))}</h1>'
    if run.get("demo"):
        body += '<aside><strong>SYNTHETIC DEMO — NOT REAL COMPANY DATA</strong></aside>'
    body += f'<p>Financial research investigation · {e(run["created"][:10])}</p><p class="badge">{e(run["status"].replace("_", " "))}</p></header>'
    if run["status"] != "completed":
        body += '<aside>No fully supported discovery was established. The hypotheses below retain their unresolved or rejected status.</aside>'
    body += '<section><h2>Research scope</h2><p>Public-source investigation of geographic exposure, business model changes and regulatory developments. '
    body += 'Quotes and financial calculations are mechanically checked. Interpretation, source classification and causal relevance require judgment.</p>'
    usage = run.get("usage", {})
    body += f'<p>{len(sources)} sources · {len(facts)} anchored facts · {usage.get("searches", 0)} searches · {usage.get("model_calls", 0)} model calls</p></section>'
    for index, f in enumerate(run["findings"], 1):
        body += f'<article><p class="eyebrow">Finding {index} · {e(f["angle"])}</p><h2>{e(f["title"])}</h2>'
        body += f'<p class="badge {e(f["status"])}">{e(f["status"])} · {e(f["strength"])} evidence</p>'
        body += '<h3>The discovery</h3><p>' + e(f["claim"]) + ' ' + references(f["discovery_evidence"]) + '</p>'
        body += '<h3>Why it matters</h3><ul>' + ''.join('<li>' + e(b["text"]) + ' ' + references(b["evidence"]) + '</li>' for b in f["why_it_matters"]) + '</ul>'
        body += '<h3>Timeline</h3><table><thead><tr><th>Date</th><th>Development</th><th>Evidence</th></tr></thead><tbody>'
        for point in sorted(f["timeline"], key=lambda p: p["date"]):
            body += f'<tr><td>{e(point["date"])}</td><td>{e(point["description"])}</td><td>{references(point["evidence"])}</td></tr>'
        body += '</tbody></table>' if f["timeline"] else '<tr><td colspan="3">No sufficiently dated event established.</td></tr></tbody></table>'
        body += '<h3>Numbers and calculations</h3>'
        if not f["calculations"]:
            body += '<p>No validated derived calculation was retained. Financial materiality remains a limitation.</p>'
        for calc in f["calculations"]:
            body += f'<div class="calculation"><strong>{e(calc["purpose"])}</strong><p>{e(calc["result"])} {e(calc["unit"])}</p>'
            body += f'<code>{e(calc["formula"])}</code><p>Inputs: {e(", ".join(calc["input_values"]))}; periods: {e(", ".join(calc["input_periods"]))}</p>{references(calc["inputs"])}</div>'
        body += '<h3>Supporting and opposing evidence</h3><p>Supporting: ' + references(f["evidence"]) + '</p><p>Opposing: ' + (references(f["opposing_evidence"]) or 'No anchored opposing fact retained; this does not prove none exists.') + '</p>'
        body += '<h3>Strongest counterargument</h3><p>' + e(f["counterarguments"][0]) + ' ' + references(f["counterargument_evidence"]) + '</p>'
        body += '<h3>What would change our mind</h3><p>' + e(f["falsification"]) + '</p>'
        body += '<h3>Evidence strength</h3><p><strong>' + e(f["strength"]) + '</strong>: ' + e(f["strength_reason"]) + '</p>'
        body += '<h3>Alternative explanations tested</h3><ul>'
        for test in f["skeptic"]["alternative_tests"]:
            body += '<li>' + e(test["explanation"]) + ' — ' + e(test["outcome"].replace('_', ' ')) + ' ' + references(test["evidence"]) + '</li>'
        body += '</ul><h3>Limitations</h3><ul>' + ''.join('<li>' + e(p) + '</li>' for p in f["limitations"]) + '</ul></article>'
    body += '<section><h2>Collected sources</h2><p>Collection alone does not establish evidence. '
    body += 'Only passages in the evidence register passed fact validation. Repeated files do not establish independent corroboration.</p>'
    if not sources:
        body += '<p>No source documents were collected.</p>'
    else:
        body += '<table><thead><tr><th>Source</th><th>Publication date</th><th>Validation</th><th>Content</th></tr></thead><tbody>'
        seen_hashes = set()
        for sid, src in sources.items():
            count = sum(fact['source_id'] == sid for fact in facts.values())
            content_hash = src.get('original_sha256') or src.get('sha256')
            repeated = bool(content_hash and content_hash in seen_hashes)
            if content_hash:
                seen_hashes.add(content_hash)
            url = safe_url(src['url'])
            label = e(src['title'])
            if url:
                label = f'<a href="{e(url)}" rel="noreferrer">{label}</a>'
            validation = f'{count} accepted fact(s)' if count else 'No accepted facts; not supporting evidence'
            content = 'Repeated file content' if repeated else 'First occurrence; origin independence unverified'
            body += f'<tr><td>{label}<br>{e(src["publisher"])}</td><td>{e(src["published"] or "Unknown")}</td><td>{e(validation)}</td><td>{e(content)}</td></tr>'
        body += '</tbody></table>'
    body += '</section><section><h2>Evidence register</h2>'
    if not facts:
        body += '<p>No extracted facts passed validation. The collected sources above cannot substantiate a discovery in this report.</p>'
    for fid, fact in facts.items():
        src = sources[fact["source_id"]]
        url = safe_url(src["url"])
        if url and urlparse(url).path.lower().endswith('.pdf'):
            url = url.split('#')[0] + '#page=' + str(fact["page"])
        link = f'<a href="{e(url)}" rel="noreferrer">Open original source</a>' if url else 'Local archived source'
        body += f'<div class="fact" id="fact-{e(fid)}"><h3>{e(fid)} · {e(src["title"])}</h3><p>{e(src["publisher"])} · '
        body += f'Published: {e(src["published"] or "unknown")} · Retrieved: {e(src.get("retrieved_at", "local archive"))} · Page {e(fact["page"])}</p>'
        body += f'<p>{e(fact["statement"])}</p><blockquote>{e(fact["quote"])}</blockquote><p>{link}</p>'
        body += f'<details><summary>Provenance</summary><p>Origin classification: {e(src.get("source_kind", "unclassified"))}; '
        body += f'{e(src.get("origin_group", "unknown"))} (model-assessed)</p><code>Archived text/file SHA-256: {e(src["sha256"])}</code>'
        body += f'<p>Original downloaded SHA-256: {e(src.get("original_sha256", src["sha256"]))}</p></details></div>'
    body += '</section>'
    if challenges:
        body += '<section><h2>Subsequent questions</h2><p>These are local archive searches, not newly verified model conclusions.</p>'
        for challenge in challenges:
            body += '<h3>' + e(challenge["question"]) + '</h3><p>Status: unresolved</p>'
            for match in challenge["payload"]["matches"]:
                body += '<p>' + e(match["title"]) + ', page ' + e(match["page"]) + '</p><blockquote>' + e(match["passage"]) + '</blockquote>'
        body += '</section>'
    body += '<section><h2>Research limitations</h2><ul>' + ''.join('<li>' + e(w) + '</li>' for w in run["warnings"]) + '</ul></section>'
    body += '<details><summary>Investigation activity and reproducibility</summary><pre>' + e(json.dumps({"run_id": run["id"], "parameters": run["parameters"], "usage": usage, "events": run["events"]}, indent=2)) + '</pre></details>'
    css = ('body{font:16px/1.65 system-ui,sans-serif;color:#172b3a;background:#edf2f5;margin:0}main{max-width:1050px;margin:auto;padding:36px 24px}'
        'header,article,section{background:white;padding:28px 36px;margin-bottom:24px;border:1px solid #d6dfe5;border-radius:8px}'
        'h1{font-size:34px;line-height:1.2}h2{font-size:24px;line-height:1.3}h3{font-size:17px;margin-top:26px}p,li{max-width:85ch}'
        '.eyebrow{font-size:12px;letter-spacing:.1em;text-transform:uppercase}.badge{display:inline-block;background:#fff0ca;padding:4px 12px;border-radius:4px}'
        '.supported{background:#d8f0e5}.rejected{background:#f9dddd}aside{padding:20px;background:#fff0ca;margin-bottom:24px}'
        'table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:12px;border:1px solid #d6dfe5}th{background:#eef3f6}'
        'a{color:#14598b;overflow-wrap:anywhere}.ref{font-size:12px}.fact{border-top:1px solid #d6dfe5;padding:14px 0;scroll-margin-top:20px}'
        'blockquote{margin:12px 0;padding:12px 20px;background:#f4f7f9;border-left:3px solid #748b9d;white-space:pre-wrap}'
        'code,pre{font-size:12px;white-space:pre-wrap;overflow-wrap:anywhere}.calculation{padding:16px;background:#f4f7f9;margin:12px 0}'
        '@media print{body{background:white}main{padding:0}article,section{border:none}a{color:inherit}details{display:block}}'
        '@media(max-width:650px){main{padding:12px}header,article,section{padding:18px}table{font-size:12px}}')
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; base-uri \'none\'">'
        '<title>PHARMA-SCOPE research report</title><style>' + css + '</style></head><body><main>' + body + '</main></body></html>')


def markdown(run, challenges=()):
    lines = [f'# PHARMA-SCOPE / {run["company"]}', '', f'Status: {run["status"]}', '']
    for f in run["findings"]:
        lines += [f'## {f["title"]}', '', f'{f["strength"]} evidence — {f["status"]}', '', f["claim"], '', '### Why it matters', '']
        lines += ['- ' + b["text"] + ' [' + ', '.join(b["evidence"]) + ']' for b in f["why_it_matters"]]
        lines += ['', '### Timeline', ''] + ['- ' + t["date"] + ': ' + t["description"] + ' [' + ', '.join(t["evidence"]) + ']' for t in f["timeline"]]
        lines += ['', '### Numbers', ''] + ['- ' + c["purpose"] + ': ' + c["result"] + ' ' + c["unit"] + '; ' + c["formula"] for c in f["calculations"]]
        lines += ['', '### Counterargument', '', f["counterarguments"][0], '', '### Falsification condition', '', f["falsification"],
                  '', '### Evidence strength', '', f["strength_reason"], '', '### Limitations', ''] + ['- ' + p for p in f["limitations"]] + ['']
    sources = {s["id"]: s for s in run["sources"]}
    lines += ['## Evidence register', '']
    for fact in run["facts"]:
        src = sources[fact["source_id"]]
        lines += [f'### {fact["id"]}', '', f'{src["title"]}; page {fact["page"]}; published {src["published"] or "unknown"}',
                  '', f'> {fact["quote"]}', '', src["url"], '', 'SHA-256: ' + src["sha256"], '']
    lines += ['## Research limitations', ''] + ['- ' + w for w in run["warnings"]]
    return '\n'.join(lines) + '\n'


def from_geography(run):
    from .presentation import headline, significance
    facts = [{**r, "statement": f"{r['region']} revenue in FY{r['period']}: {r['value']} {r['currency']} {r['unit']}"} for r in run["observations"]]
    findings = []
    for f in run["findings"]:
        calculations, timeline = [], []
        for c in f["calculations"]:
            points = c["timeline"]
            for p in points:
                timeline.append({"date": "FY" + str(p["period"]), "description": f"Revenue share: {p['share_pct']:.2f}%",
                                 "evidence": [p["regional_observation"], p["total_observation"]]})
            calculations.append({"purpose": "Change in revenue share (percentage points)", "result": str(c["delta_pp"]), "unit": "pp",
                "formula": c["formula"], "input_values": [points[0]["regional_revenue"], points[0]["total_revenue"], points[-1]["regional_revenue"], points[-1]["total_revenue"]],
                "input_periods": [str(points[0]["period"]), str(points[-1]["period"])], "inputs": f["evidence"]})
        findings.append({**f, "title": headline(f), "angle": "geography", "status": "unresolved", "discovery_evidence": f["evidence"],
            "why_it_matters": [{"text": text, "evidence": f["evidence"]} for text in significance(f)],
            "timeline": timeline, "calculations": calculations, "opposing_evidence": [], "counterargument_evidence": f["evidence"],
            "strength_reason": "Arithmetic and source passages checked. These are issuer-origin disclosures; independent corroboration and causal tests remain missing.",
            "limitations": ["Offline descriptive analysis; explanations are untested.", "The falsification condition concerns historical corrections, not a tested forward-looking causal hypothesis."],
            "skeptic": {"alternative_tests": [{"explanation": text, "outcome": "unresolved", "evidence": []} for text in f["counterarguments"]]}})
    return {**run, "facts": facts, "findings": findings, "status": "insufficient_evidence"}
