"""Terminal dashboard summaries drawn only from saved research data."""
from collections import defaultdict
from decimal import Decimal, InvalidOperation

from rich.text import Text

from .presentation import series, plain_log

CYAN = '#25d9e8'
MUTED = '#8a9bb4'
AMBER = '#efc56e'


def cards(run):
    facts = run.get('facts', run.get('observations', []))
    numeric = [f for f in facts if f.get('value') not in ('', None)]
    findings = run.get('findings', [])
    supported = sum(f['status'] == 'supported' for f in findings)
    usage, limits = run.get('usage', {}), run.get('parameters', {})
    return [
        ('Sources Archived', str(len(run.get('sources', []))), 'Document count, not origins'),
        ('Financial Inputs', str(len(numeric)), f'{len(facts)} source-anchored inputs'),
        ('Research Findings', str(len(findings)), f'{supported} supported · {len(findings) - supported} other'),
        ('Model Calls', f"{usage.get('model_calls', 0)} / {limits.get('model_calls', '—')}",
         f"{usage.get('searches', 0)} searches · " + ('Offline demo' if run.get('demo') else 'Public sources')),
    ]


def card_text(card, compact=False):
    title, value, note = card
    text = Text(title + '\n', style=MUTED)
    text.append(value + '\n', style='bold ' + CYAN)
    if not compact:
        text.append(note, style=MUTED)
    return text


def chart(run, finding, compact=False):
    """Show reported figures, never fabricated prices or confidence percentages."""
    text = Text('Financial Snapshot\n', style='bold ' + CYAN)
    points = series(finding) if finding else []
    label = 'Revenue Share (%)'
    values = [(f"FY{p['period']}", Decimal(str(p['share_pct']))) for p in points]
    if not values:
        groups = defaultdict(list)
        cited = set(finding.get('evidence', [])) if finding else set()
        for fact in run.get('facts', []):
            if not fact.get('value') or not fact.get('fiscal_period'):
                continue
            key = tuple(fact.get(k, '') for k in ('entity', 'metric', 'currency', 'unit', 'basis', 'definition'))
            groups[key].append(fact)
        candidates = [(key, rows) for key, rows in groups.items() if len({r['fiscal_period'] for r in rows}) >= 2]
        candidates.sort(key=lambda item: (-sum(r['id'] in cited for r in item[1]), -len(item[1]), item[0]))
        if candidates:
            key, rows = candidates[0]
            label = f'{key[1]} · {key[2]} {key[3]}'.strip()
            unique = {r['fiscal_period']: r for r in rows}
            # Conflicting values for a period must not silently turn into a chart.
            if any(len({r['value'] for r in rows if r['fiscal_period'] == period}) > 1 for period in unique):
                text.append('Conflicting figures: chart withheld.\n', style=AMBER)
                return text
            try:
                values = [(period, Decimal(row['value'])) for period, row in sorted(unique.items())]
            except InvalidOperation:
                values = []
    if not values:
        text.append('\nNo comparable financial series yet.\n', style=MUTED)
        text.append('Collected documents alone do not establish a trend.\n\n', style=MUTED)
        text.append('Inspect the pipeline and source ledger for progress.', style=AMBER)
        return text
    text.append(label[:76] + '\n', style=MUTED)
    if compact and len(values) > 2:
        values = values[:1] + values[-1:]
    elif len(values) > 5:
        values = values[:1] + values[-4:]
    scale = max(abs(value) for _, value in values) or Decimal(1)
    for period, value in values:
        length = max(0, min(22, round(abs(value) / scale * 22)))
        text.append(f'{period:11} ', style=MUTED)
        text.append('█' * length + '░' * (22 - length), style=CYAN)
        text.append(f' {value:,.2f}\n')
    text.append('Quoted inputs · review comparability' if compact else 'Reported inputs · comparisons remain subject to evidence review', style=MUTED)
    return text


def source_ledger(run):
    text = Text('Source Ledger\n', style='bold ' + CYAN)
    seen = set()
    if not run.get('sources'):
        text.append('\nNo documents archived yet.', style=MUTED)
    for source in run.get('sources', [])[:5]:
        text.append('\n' + source['title'][:65] + '\n', style='#dce6f3')
        text.append((source.get('published') or 'Date unknown') + ' · ' + source['publisher'] + '\n', style=MUTED)
        fingerprint = source.get('original_sha256') or source.get('sha256')
        text.append(('Repeated file' if fingerprint and fingerprint in seen else 'Independence unverified') + '\n', style=MUTED)
        if fingerprint:
            seen.add(fingerprint)
    if len(run.get('sources', [])) > 5:
        text.append(f"\n+ {len(run['sources']) - 5} more · E: source details", style=MUTED)
    return text


def activity_stream(run):
    text = Text('Research Stream · UTC\n', style='bold ' + CYAN)
    for event in run.get('events', [])[-5:]:
        text.append('\n' + event.get('at', '')[11:19] + ' ' + event['stage'].replace('_', ' ').title() + '\n', style=MUTED)
        text.append(plain_log(event['message'])[:180] + '\n', style='#b7c7da')
    if not run.get('events'):
        text.append('No recorded activity.', style=MUTED)
    return text


PIPELINE_HELP = """1. Identify the company
Search for public investor-relations material and match the name/ticker to downloaded text. Index membership is not automatically verified.

2. Plan the research
Gemini (or the configured model) chooses geographic exposure, business-model or regulatory questions.

3. Search and download
DDGS tries DuckDuckGo then Bing when configured; Brave/Tavily are optional adapters. Search snippets are leads, not evidence. Follow bounded links from official financial indexes, including linked CDN PDFs. No paid financial database is bundled.

4. Extract and validate
BeautifulSoup reads HTML; PyMuPDF reads PDF text. Selected physical pages go to the model. Exact quotes, numeric values and separate table headers are checked locally. Scans need OCR; blocked sites and search failures leave coverage gaps.

5. Calculate and challenge
Python Decimal performs comparable calculations. Hypotheses need financial inputs and a valid calculation. Follow-up searches seek supporting AND opposing evidence; a skeptic tests alternatives and chronology.

6. Review and publish
A separate model pass checks whether claims follow from evidence. Independent-origin checks and future falsification requirements gate publication. SQLite stores checkpoints and source archives. Incomplete research exports an explicitly partial report.

Limits
Source classification and interpretation remain fallible. This is public-document research, not a real-time price feed. Evidence ratings are categories, not probability estimates. The question box searches the local archive; it does not execute shell commands or start new live research.
"""
