"""Plain-language views shared by the terminal and its tests."""


def series(finding):
    return next((c["timeline"] for c in finding.get("calculations", []) if "timeline" in c), [])


def headline(finding):
    points = series(finding)
    if points:
        region = finding["title"].split(":", 1)[0]
        a, b = points[0], points[-1]
        direction = "rose" if b["share_pct"] > a["share_pct"] else "fell"
        return f"{region}'s share of revenue {direction} {a['share_pct']:.0f}% → {b['share_pct']:.0f}% (FY{str(a['period'])[-2:]}–FY{str(b['period'])[-2:]})"
    if finding["status"] == "unresolved" and not finding.get("angle"):
        return "These reports cannot yet be compared reliably"
    return finding["title"]


def plain_status(finding):
    value = finding["status"]
    if value.startswith("observed"):
        return "Observed, cause not yet explained"
    return {"supported": "Supported by the collected evidence", "rejected": "Contradicted or rejected",
            "unresolved": "Unresolved — more evidence needed"}.get(value, value.replace("_", " ").capitalize())


def significance(finding):
    if finding.get("why_it_matters"):
        return [b["text"] for b in finding["why_it_matters"]]
    points = series(finding)
    if not points:
        return ["The figures may describe different reporting boundaries.", "A large apparent change could come from a reporting change.",
                "Comparable figures are needed before interpreting the business."]
    a, b = points[0], points[-1]
    region = finding["title"].split(":", 1)[0]
    delta = b["share_pct"] - a["share_pct"]
    growth = (float(b["regional_revenue"]) / float(a["regional_revenue"]) - 1) * 100 if float(a["regional_revenue"]) else None
    return [f"{region} contributed about {b['share_pct']:.0f} of every 100 revenue units, compared with {a['share_pct']:.0f} previously.",
            f"Its contribution changed by {abs(delta):.2f} percentage points across the reported period.",
            (f"Reported regional revenue changed by {growth:+.1f}%; revenue share alone does not explain why." if growth is not None else "The starting revenue is zero, so a growth percentage cannot be calculated."),
            "Currency effects and changes in the business still need to be tested before assigning a cause."]


def alternatives(finding):
    if finding.get("skeptic"):
        return [(t["explanation"], "Tested — ruled out" if t["outcome"] == "ruled_out" else
                 "Tested — supported alternative" if t["outcome"] == "supported" else "Not resolved",
                 "green" if t["outcome"] == "ruled_out" else "amber") for t in finding["skeptic"]["alternative_tests"]]
    values = [(label, "Untested", "grey") for label in ["Currency translation", "Acquisitions", "Divestitures", "Region reclassification"]]
    values.append(("Other regions changing", "Partly tested — revenue shares compared; cause unresolved", "amber") if series(finding) else
                  ("Reporting definitions changed", "Detected — comparison withheld", "amber"))
    return values


def evidence_criteria(run, finding):
    blocked = not series(finding) and not finding.get("angle")
    reasons = [("Credibility", "Demo only" if run["demo"] else "Source passages retained; publisher authenticity needs review"),
        ("Independence", "Not established"), ("Consistency", "Data differences remain" if blocked else "Source quotes and arithmetic checked"),
        ("Comparability", "Different reporting definitions or incomplete figures" if blocked else "Reported basis and units checked; semantic review still needed"),
        ("Contradictions", "Alternatives remain unresolved")]
    if finding.get("strength_reason"):
        reasons[1] = ("Independence", finding["strength_reason"])
        reasons[4] = ("Contradictions", finding.get("skeptic", {}).get("reasoning", "See alternative tests"))
    return reasons


def plain_log(message):
    return message.replace("blocking issue(s)", "data problem(s) that stop analysis").replace("reconciliation", "whether the figures add up").replace("configured threshold", "minimum change selected for this investigation")
