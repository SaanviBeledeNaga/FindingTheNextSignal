from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
import json
import re

from .store import Store, now, uid

SCALE = {"units": 1, "thousand": 1000, "lakh": 100000, "million": 1000000,
         "crore": 10000000, "billion": 1000000000}


def amount(row):
    return Decimal(row["value"]) * SCALE[row["unit"]]


def discover(store: Store, company: str, threshold=5.0, years=5, emit=None) -> dict:
    company = company.upper()
    rows = store.observations(company)
    if not rows:
        raise ValueError(f"No observations for {company}. Ingest sources and import metrics, or run demo.")
    if not 0 < threshold <= 100 or years < 2:
        raise ValueError("threshold must be in (0,100]; years must be at least 2.")
    if len({r["demo"] for r in rows}) != 1:
        raise ValueError("Demo and real observations cannot be combined in one investigation.")
    sources = {s["id"]: s for s in store.sources(company)}
    run = {"id": uid("run"), "company": company, "created": now(), "status": "running",
           "demo": bool(rows[0]["demo"]), "engine": "bounded deterministic geography investigation",
           "parameters": {"threshold_pp": threshold, "years": years}, "events": [], "findings": [],
           "warnings": [], "observations": rows, "sources": list(sources.values())}

    def event(stage, message):
        entry = {"at": now(), "stage": stage, "message": message}
        run["events"].append(entry)
        store.save_run(run)
        if emit:
            emit(entry)

    event("profile", f"Loaded {len(rows)} observations from {len(sources)} archived disclosures.")
    end = max(r["period"] for r in rows)
    rows = [r for r in rows if r["period"] >= end - years + 1]
    periods = sorted({r["period"] for r in rows})
    if len(periods) < 2:
        run["warnings"].append("At least two fiscal periods are required for a comparison.")
    if len(periods) < years:
        run["warnings"].append(f"Only {len(periods)} of {years} requested fiscal periods have observations; no interpolation performed.")
    groups = defaultdict(list)
    for row in rows:
        groups[(row["period"], row["region"])].append(row)
    unique, conflicts = {}, []
    for key, candidates in groups.items():
        signatures = {(amount(r), r["currency"], r["basis"], r["definition"]) for r in candidates}
        if len(signatures) > 1:
            conflicts.append(f"Conflicting disclosures for FY{key[0]} / {key[1]}; resolve or restate before analysis.")
        else:
            unique[key] = candidates[0]
    issues = list(conflicts)
    for period in periods:
        total = unique.get((period, "Total"))
        regions = [r for (p, region), r in unique.items() if p == period and region != "Total"]
        if total is None:
            issues.append(f"FY{period}: missing unambiguous Total observation.")
            continue
        if amount(total) <= 0:
            issues.append(f"FY{period}: total revenue must be positive.")
        if not regions:
            issues.append(f"FY{period}: missing geographic observations.")
        if any((r["currency"], r["basis"], r["definition"]) !=
               (total["currency"], total["basis"], total["definition"]) for r in regions):
            issues.append(f"FY{period}: geographic rows and Total have different reporting definitions, currencies or bases.")
        if abs(sum((amount(r) for r in regions), Decimal(0)) - amount(total)) > max(abs(amount(total)) * Decimal("0.01"), Decimal(1)):
            issues.append(f"FY{period}: geographic rows do not reconcile to Total within 1%; confirm exhaustive, nonoverlapping regions.")
    if len({(r["currency"], r["basis"], r["definition"]) for r in rows}) > 1:
        issues.append("Reporting definition, currency or consolidation basis changes across the selected series. Recast comparable figures first.")
    region_sets = [{r["region"] for r in rows if r["period"] == p} for p in periods]
    if region_sets and any(s != region_sets[0] for s in region_sets):
        issues.append("Geographic categories change across periods; a stable geographic mapping is required.")
    event("validate", f"Checked units, totals, duplicate disclosures and comparability: {len(issues)} blocking issue(s).")
    if issues:
        run["warnings"].extend(issues)
        run["findings"].append({"id": uid("finding"), "title": "Comparison withheld: disclosures are not comparable",
            "status": "unresolved", "strength": "Weak", "claim": "A reliable geographic drift conclusion cannot be published from these inputs.",
            "calculations": [], "evidence": [r["id"] for r in rows], "counterarguments": issues,
            "falsification": "Provide reconciled, consistently defined figures covering the same reporting basis and geography.",
            "next_steps": ["Check original tables and comparative restatements.", "Resolve duplicate or conflicting disclosures."]})
    elif len(periods) >= 2:
        first, last = periods[0], periods[-1]
        for region in sorted(region_sets[0] - {"Total"}):
            a, b = unique[(first, region)], unique[(last, region)]
            ta, tb = unique[(first, "Total")], unique[(last, "Total")]
            sa, sb = amount(a) / amount(ta) * 100, amount(b) / amount(tb) * 100
            delta = sb - sa
            if abs(delta) < Decimal(str(threshold)):
                continue
            timeline, evidence = [], []
            for period in periods:
                r, total = unique[(period, region)], unique[(period, "Total")]
                timeline.append({"period": period, "regional_revenue": str(amount(r)), "total_revenue": str(amount(total)),
                                 "currency": r["currency"], "share_pct": round(float(amount(r) / amount(total) * 100), 4),
                                 "regional_observation": r["id"], "total_observation": total["id"]})
                evidence.extend([r["id"], total["id"]])
            direction = "increased" if delta > 0 else "decreased"
            claim = f"{region} share of reported revenue {direction} from {sa:.2f}% in FY{first} to {sb:.2f}% in FY{last} ({delta:+.2f} percentage points)."
            run["findings"].append({"id": uid("finding"), "title": f"{region}: {delta:+.2f} pp revenue mix shift",
                "status": "observed; cause unresolved", "strength": "Moderate", "claim": claim,
                "hypothesis": f"Investigate whether a change in {region} business activity explains this revenue mix shift.",
                "calculations": [{"formula": "share = regional_revenue / total_revenue * 100; delta_pp = last_share - first_share",
                                  "delta_pp": round(float(delta), 4), "timeline": timeline}],
                "evidence": evidence,
                "counterarguments": ["Revenue share can move because other regions change, even without a change in this region's strategy.",
                    "FX translation, acquisitions, divestitures and geographic reclassification remain untested.",
                    "Issuer disclosures are one origin, even when several reports repeat the same claim. Independent corroboration is missing.",
                    "Chronology alone cannot establish regulatory causation."],
                "falsification": "A comparable restatement or corrected source figure reduces the absolute mix shift below the configured threshold.",
                "next_steps": ["Find constant-currency and acquisition-adjusted disclosures.",
                               "Confirm region definitions and reporting boundaries in footnotes.",
                               "Seek independently originated evidence before attributing a cause."]})
    event("discover", f"Created {len(run['findings'])} finding(s) at a {threshold:g} pp threshold.")
    event("skeptic", "Tested reconciliation and comparability; attached unresolved alternatives. No causal claims or independent corroboration inferred.")
    run["status"] = "completed"
    event("publish", "Saved evidence snapshot and calculation inputs.")
    return run


def challenge(store: Store, run_id: str, finding_id: str, question: str):
    run = store.run(run_id)
    finding = next((f for f in run["findings"] if f["id"] == finding_id), None)
    if finding is None:
        raise ValueError("Finding does not belong to this run.")
    if not question.strip():
        raise ValueError("Challenge cannot be empty.")
    stop = {"could", "would", "this", "that", "have", "with", "what", "does", "from", "were", "been", "explain"}
    keywords = set(re.findall(r"[a-z]{3,}", question.lower())) - stop
    if any(k in keywords for k in {"currency", "forex", "fx"}):
        keywords |= {"currency", "exchange", "translation", "fx"}
    matches = []
    # Search all currently ingested material: newly added contradictory reports are eligible.
    for source in store.sources(run["company"]):
        if bool(source["demo"]) != run["demo"]:
            continue
        for page_no, page in enumerate(source["pages"], 1):
            for passage in re.split(r"\n\s*\n", page):
                score = len(keywords & set(re.findall(r"[a-z]{2,}", passage.lower())))
                if score:
                    matches.append({"source_id": source["id"], "title": source["title"], "page": page_no,
                                    "passage": passage[:3000], "score": score, "url": source["url"], "sha256": source["sha256"]})
    matches.sort(key=lambda m: (-m["score"], m["source_id"], m["page"]))
    result = {"status": "unresolved", "method": "keyword retrieval over archived evidence; relevance is not verification",
              "matches": matches[:8], "next_step": "Review passages and obtain comparable adjusted figures. This challenge does not change the finding rating."}
    cid = uid("challenge")
    store.db.execute("INSERT INTO challenges VALUES (?,?,?,?,?,?)", (cid, run["id"], finding_id, now(), question, json.dumps(result)))
    store.db.commit()
    return {"id": cid, "question": question, **result}
