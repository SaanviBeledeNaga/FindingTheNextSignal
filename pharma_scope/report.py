from html import escape
import json
from pathlib import Path
from urllib.parse import urlparse


def markdown(run, challenges=()):
    if run.get("kind") == "research":
        from .research_report import markdown as research_markdown
        return research_markdown(run, challenges)
    lines = [f"# PHARMA-SCOPE / {run['company']}", "",
             "**SYNTHETIC DEMO - NOT REAL COMPANY DATA**" if run["demo"] else "Research dossier / source-grounded observations", "",
             f"Run: {run['id']} | {run['created']} | {run['status']}", "",
             f"Engine: {run['engine']}", ""]
    obs = {r["id"]: r for r in run["observations"]}
    sources = {s["id"]: s for s in run["sources"]}
    for warning in run["warnings"]:
        lines += [f"> {warning}", ""]
    if not run["findings"]:
        lines += ["No findings exceeded the configured threshold. This does not establish that no business change occurred.", ""]
    for f in run["findings"]:
        lines += [f"## {f['title']}", "", f"{f['id']} / {f['status']} / Evidence: {f['strength']}", "", f["claim"], ""]
        if f.get("hypothesis"):
            lines += [f"Hypothesis: {f['hypothesis']}", ""]
        for calc in f["calculations"]:
            lines += [f"Formula: `{calc['formula']}`", "", "| FY | Regional revenue (base units) | Total revenue (base units) | Share |",
                      "|---|---:|---:|---:|"]
            for point in calc["timeline"]:
                lines += [f"| {point['period']} | {point['regional_revenue']} {point['currency']} | {point['total_revenue']} {point['currency']} | {point['share_pct']:.2f}% |"]
            lines += [""]
        lines += ["### Skeptic", ""] + [f"- {s}" for s in f["counterarguments"]]
        lines += ["", f"Falsification condition: {f['falsification']}", "", "### Next evidence to collect", ""]
        lines += [f"- {s}" for s in f["next_steps"]] + ["", "### Evidence", ""]
        for oid in f["evidence"]:
            row = obs[oid]
            src = sources[row["source_id"]]
            lines += [f"- {oid}: {src['title']}, physical page {row['page']}; {src['publisher']}; {src['published']}",
                      f"  - Source: {src['url'] or 'local archived source'}", f"  - SHA-256: {src['sha256']}",
                      f"  - Passage: {row['quote']}"]
        lines += [""]
    if challenges:
        lines += ["## Challenges", ""]
        for c in challenges:
            lines += [f"### {c['question']}", "", "Status: unresolved. Retrieved passages require review.", ""]
            for m in c["payload"]["matches"]:
                lines += [f"- {m['title']}, page {m['page']}: {m['passage']}"]
            lines += [""]
    lines += ["## Investigation activity", ""] + [f"- {e['stage']}: {e['message']}" for e in run["events"]]
    return "\n".join(lines) + "\n"


def export(store, run, destination: Path, format="html"):
    from .research_policy import publication_view
    run = publication_view(run)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    challenges = store.challenges(run["id"])
    if format == "json":
        content = json.dumps({**run, "challenges": challenges}, indent=2)
    elif format == "md":
        content = markdown(run, challenges)
    elif run.get("kind") == "research":
        from .research_report import html
        content = html(run, challenges)
    else:
        from .research_report import html, from_geography
        content = html(from_geography(run), challenges)
    destination.write_text(content, encoding="utf-8")
    return destination.resolve()
