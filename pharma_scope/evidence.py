from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
import re
from urllib.parse import urlparse

from .ingest import norm
from .store import digest

SCALES = {"units": 1, "thousand": 1000, "lakh": 100000, "million": 1000000, "crore": 10000000, "billion": 1000000000,
          "%": 1, "percent": 1, "days": 1, "ratio": 1}


class IdentityResolutionError(ValueError):
    """A safe, specific identity-validation error suitable for the dashboard."""
    pass


def identity_matches(company_input, profile):
    """All distinctive requested words must match; 'Apollo' alone is insufficient."""
    canonical=lambda value: re.sub(r'[^a-z0-9]','',str(value).casefold())
    generic={'limited','ltd','inc','incorporated','enterprise','enterprises','industries','industry','company','corporation','co'}
    tokens=[w for w in re.findall(r'[a-z0-9]+',str(company_input).casefold()) if len(w)>=3 and w not in generic]
    target=canonical(profile.get('name','')+' '+profile.get('symbol',''))
    stem=lambda word: word[:-1] if len(word)>6 and word.endswith('s') else word
    return bool(tokens) and all(stem(w) in target for w in tokens)


def company_financial_facts(facts, profile):
    """Keep other entities' financial statements out of the target's quantitative evidence."""
    def name_key(value):
        words = re.findall(r'[a-z0-9]+', str(value).casefold())
        return ''.join(w for w in words if w not in {'limited', 'ltd', 'inc', 'incorporated', 'corporation'})
    names = [profile.get('name', ''), *profile.get('aliases', []), *profile.get('subsidiaries', [])]
    allowed = {name_key(name) for name in names if name_key(name)}
    kept, errors = [], []
    for fact in facts:
        if fact.get('kind') == 'financial' and fact.get('value') and name_key(fact.get('entity', '')) not in allowed:
            errors.append('financial entity is outside the resolved company/subsidiary scope: ' + str(fact.get('entity', 'Unknown')))
        else:
            kept.append(fact)
    return kept, errors


def anchored_identity(profile, company_input, sources):
    """Short company labels are valid identity evidence when name/ticker also match."""
    def canonical(value):
        return re.sub(r"[^a-z0-9]", "", value.casefold())
    name, symbol = profile["name"].strip(), profile["symbol"].strip()
    all_text = " ".join(p for source in sources for p in source["pages"])
    if len(canonical(name)) < 3 or canonical(name) not in canonical(all_text):
        raise IdentityResolutionError("Company name was not found in the collected source text.")
    symbol_grounded = len(canonical(symbol)) >= 3 and canonical(symbol) in canonical(all_text)
    input_tokens = re.findall(r"[a-z0-9]+", company_input.casefold())
    identity_text = canonical(name + " " + symbol)
    if not identity_matches(company_input,profile):
        raise IdentityResolutionError("Collected company identity does not match the requested name or symbol.")
    anchors = []
    for item in profile["identity_evidence"]:
        quote = str(item["quote"]).strip()
        if len(canonical(quote)) < 3:
            continue
        # Typographic apostrophes do not change identity. Retain the actual source
        # substring rather than presenting the model's normalized text as verbatim.
        normalized_quote = quote.translate(str.maketrans({'\u2019': "'", '\u2018': "'"}))
        pattern = r'\s+'.join(re.escape(part) for part in normalized_quote.split()).replace("'", "['\u2019\u2018]")
        matched = None
        for source in sources:
            if source['url'] == item['url']:
                matched = next((match for page in source['pages'] if (match := re.search(pattern, page, re.I))), None)
                if matched:
                    break
        label = canonical(quote)
        identifies_company = label in canonical(name) or canonical(name) in label or (symbol_grounded and (label in canonical(symbol) or canonical(symbol) in label))
        if matched and identifies_company and (len(norm(quote)) >= 15 or symbol_grounded):
            anchors.append({**item, 'quote': matched.group(0)})
    if not anchors:
        raise IdentityResolutionError("Company identity quotes could not be matched to a source name and ticker.")
    result = {**profile, "identity_evidence": anchors, "uncertainty": list(profile["uncertainty"])}
    domain = profile["official_domain"].strip().lower().removeprefix("www.")
    from .webtools import NON_ISSUER_DOMAINS, host_is
    if any(host_is(domain, directory) for directory in NON_ISSUER_DOMAINS):
        result['official_domain'] = ''
        result['uncertainty'].append('A report directory, exchange or regulator cannot be used as the issuer website; placeholder domain excluded.')
        domain = ''
    domain_supported = domain and any((urlparse(source["url"]).hostname or "").removeprefix("www.") == domain or
                                     any(domain in page.casefold() for page in source["pages"]) for source in sources)
    if domain and not domain_supported:
        result["official_domain"] = ""
        result["uncertainty"].append("Official domain was not found in collected evidence; inferred domain omitted.")
    return result


def date_in_quote(value, quote):
    parsed = date.fromisoformat(value)
    normalized = " " + norm(re.sub(r"[,./-]", " ", quote)) + " "
    variants = [value.replace("-", " "), f"{parsed.day} {parsed.month} {parsed.year}",
                f"{parsed.day:02d} {parsed.month:02d} {parsed.year}"]
    for month in [parsed.strftime("%B"), parsed.strftime("%b")]:
        variants.extend([f"{parsed.day} {month} {parsed.year}", f"{parsed.day:02d} {month} {parsed.year}",
                         f"{month} {parsed.day} {parsed.year}", f"{month} {parsed.day:02d} {parsed.year}"])
    return any(" " + norm(v) + " " in normalized for v in variants)


def extract_facts(source, rows):
    accepted, errors = [], []
    for row in rows:
        try:
            row = {**row, "unit": row["unit"].strip().casefold(), "basis": norm(row["basis"]),
                   "currency": row["currency"].strip().upper()}
            row['unit'] = {'crores':'crore','lakhs':'lakh','millions':'million','billions':'billion',
                           'thousands':'thousand','percentage':'percent'}.get(row['unit'],row['unit'])
            page = row["page"]
            if not 1 <= page <= len(source["pages"]):
                raise ValueError("page outside source")
            quote = row["quote"]
            if len(norm(quote)) < 15 or norm(quote) not in norm(source["pages"][page - 1]):
                raise ValueError("quote not found on cited page")
            context = list(row.get("context_evidence", []))
            header_anchor = row.get('column_header',{})
            if header_anchor.get('quote'):
                if header_anchor not in context:
                    context.append(header_anchor)
                row['context_evidence'] = context
            from .research_policy import section_scope
            local_scope = section_scope(source,page)
            if len(context) > 8:
                raise ValueError("too many table context passages")
            for anchor in context:
                cp, cq = anchor["page"], anchor["quote"]
                section_anchor = local_scope and cp==local_scope['page'] and norm(cq)==norm(local_scope['quote'])
                if not 1 <= cp <= len(source["pages"]) or (abs(cp - page) > 1 and cp != 1 and not section_anchor):
                    raise ValueError("table context must be on the same/adjacent page or document cover")
                if len(norm(cq)) < 4 or norm(cq) not in norm(source["pages"][cp - 1]):
                    raise ValueError("table context quote not found on cited page")
            reporting_text = quote + " " + " ".join(a["quote"] for a in context)
            if row["event_date"]:
                date.fromisoformat(row["event_date"])
                if not date_in_quote(row["event_date"], quote):
                    raise ValueError("full event date not supported by quote")
            if row["value"]:
                value = Decimal(row["value"])
                if not value.is_finite():
                    raise ValueError("nonfinite value")
                tokens = re.findall(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?", quote)
                if value not in [Decimal(t.replace(",", "")) for t in tokens]:
                    raise ValueError("numeric value not in quote")
                if row["unit"] not in SCALES:
                    raise ValueError("unknown unit")
                if not row["metric"] or not row["fiscal_period"] or not row["basis"] or not row["definition"]:
                    raise ValueError("numeric fact lacks reporting context")
                basis_in_quote = re.search(r'\b'+re.escape(row['basis'])+r'\b',reporting_text,re.I)
                if row['basis'] in {'standalone','consolidated'} and not basis_in_quote and not (local_scope and local_scope['basis']==row['basis']):
                    raise ValueError('Reporting basis is not anchored in quoted context or the nearest financial section.')
                if local_scope and local_scope['basis'] != row['basis'] and not basis_in_quote:
                    raise ValueError('Reporting basis conflicts with the nearest financial section.')
                period_year = re.search(r"(?:19|20)\d{2}", row["fiscal_period"])
                year = period_year[0] if period_year else ""
                short_fy = re.search(r"\bFY\s*['’]?" + re.escape(year[-2:]) + r"\b", reporting_text, re.I) if year else None
                split_fy = re.search(r"\b" + str(int(year) - 1) + r"\s*[-–/]\s*" + year[-2:] + r"\b", reporting_text) if year else None
                if not year or not (re.search(r"(?<!\d)" + year + r"(?!\d)", reporting_text) or short_fy or split_fy):
                    raise ValueError("fiscal period year not in evidence quote")
                # A number occurring somewhere in a row is insufficient: check its
                # year-column association when a multi-year header is supplied.
                header_context = [header_anchor] if header_anchor.get('quote') else context
                headers = [re.findall(r'(?<!\d)20\d{2}(?!\d)',a['quote']) for a in header_context]
                header = next((h for h in headers if len(h)>=2 and len(set(h))==len(h) and year in h),None)
                if not re.search(r'(?<!\d)20\d{2}(?!\d)',quote) and len(tokens)>=2 and not header:
                    raise ValueError('Multiple table values require a separate, unambiguous year-column header; a report title or single year cannot assign the columns.')
                if header and not re.search(r'(?<!\d)20\d{2}(?!\d)',quote):
                    if len(tokens) < len(header) or len(tokens) > len(header)+1:
                        raise ValueError('Table row is ambiguous; quote one row and its corresponding year header.')
                    columns = [Decimal(t.replace(',','')) for t in tokens[-len(header):]]
                    if columns[header.index(year)] != value:
                        raise ValueError('Financial value conflicts with its cited year-column position.')
                money_units = {"units", "thousand", "lakh", "million", "crore", "billion"}
                if row["unit"] in money_units and not row["currency"]:
                    raise ValueError("monetary fact lacks currency")
            identity = [source["id"], page, norm(quote), row["metric"], row["value"], row["fiscal_period"],
                        row["entity"], row["basis"], row["definition"], context]
            import json
            fid = "fact-" + digest(json.dumps(identity, sort_keys=True).encode())[:12]
            accepted.append({**row, "id": fid, "source_id": source["id"]})
        except (ValueError, InvalidOperation) as exc:
            errors.append(str(exc))
    return accepted, errors


def calculation(spec, facts):
    refs = spec["inputs"]
    if len(refs) != 2 or len(set(refs)) != 2 or any(fid not in facts for fid in refs):
        raise ValueError("Calculations require two known numeric fact IDs.")
    a, b = [facts[fid] for fid in refs]
    if a.get("entity") != b.get("entity"):
        raise ValueError("Calculation inputs refer to different entities.")
    if not a["value"] or not b["value"]:
        raise ValueError("Calculation input is not numeric.")
    for field in ["currency", "basis", "unit"] + (["definition"] if spec['operation'] not in {'share','margin_pct'} else []):
        if field == "unit":
            if a[field] not in SCALES or b[field] not in SCALES:
                raise ValueError("Unknown units.")
            # Different monetary scales are allowed; unlike dimensions are not.
            monetary = {"units", "thousand", "lakh", "million", "crore", "billion"}
            if a[field] != b[field] and not {a[field], b[field]} <= monetary:
                raise ValueError("Incompatible unit dimensions.")
        elif norm(a[field]) != norm(b[field]):
            raise ValueError(f"Calculation has incompatible {field}.")
    x, y = Decimal(a["value"]) * SCALES[a["unit"]], Decimal(b["value"]) * SCALES[b["unit"]]
    op = spec["operation"]
    if op in {"share", "margin_pct"}:
        if a["fiscal_period"] != b["fiscal_period"]:
            raise ValueError("Share or margin inputs must use the same fiscal period.")
        if y <= 0 or a['unit'] not in {'units','thousand','lakh','million','crore','billion'} or b['unit'] not in {'units','thousand','lakh','million','crore','billion'}:
            raise ValueError("Share/margin requires monetary inputs and a positive denominator.")
        if op == 'share' and not 0 <= x <= y:
            raise ValueError('A component share must be between zero and its total.')
        result, formula, unit = x / y * 100, "first / second * 100", "%"
    elif op == "difference":
        if a['fiscal_period'] == b['fiscal_period']:
            raise ValueError('A same-metric period difference requires distinct fiscal periods; duplicate baselines do not establish a change.')
        if a["metric"] != b["metric"]:
            raise ValueError("Difference inputs must describe the same metric.")
        result, formula, unit = y - x, "second - first", "base units" if a["unit"] in {"crore", "million", "billion", "lakh", "thousand"} else a["unit"]
    else:
        if a["metric"] != b["metric"] or a["fiscal_period"] == b["fiscal_period"]:
            raise ValueError("Growth inputs require the same metric and distinct periods.")
        if x <= 0:
            raise ValueError("Growth requires a positive starting value.")
        def period_key(value):
            match = re.fullmatch(r"(?:FY)?(\d{4})(?:[- ]?Q([1-4]))?", value, re.I)
            if not match:
                raise ValueError("Growth periods must use YYYY, FYyyyy or FYyyyy-Qn.")
            return int(match[1]), int(match[2]) if match[2] else 0
        start, end = period_key(a["fiscal_period"]), period_key(b["fiscal_period"])
        if start >= end or start[1] != end[1]:
            raise ValueError("Growth periods must progress forward and have comparable annual/quarterly durations.")
        if op == "growth_pct":
            result, formula, unit = (y / x - 1) * 100, "(second / first - 1) * 100", "%"
        elif op == "cagr_pct":
            if spec["years"] <= 0 or y < 0:
                raise ValueError("CAGR needs a positive year interval and nonnegative end value.")
            if start[1] or end[1] or spec["years"] != end[0] - start[0]:
                raise ValueError("CAGR year interval does not match the annual fiscal periods.")
            result = ((y / x) ** (Decimal(1) / Decimal(spec["years"])) - 1) * 100
            formula, unit = "((second / first) ** (1 / years) - 1) * 100", "%"
        else:
            raise ValueError("Unknown operation.")
    return {**spec, "result": str(round(result, 6)), "unit": unit, "formula": formula,
            "input_values": [str(x), str(y)], "input_periods": [a["fiscal_period"], b["fiscal_period"]]}


def origin(source, profile):
    host = (urlparse(source["url"]).hostname or source["publisher"]).lower().removeprefix("www.")
    official = profile.get("official_domain", "").lower().removeprefix("www.")
    kind = source.get("source_kind", "other")
    group = norm(source.get("origin_group", ""))
    # Exchange filings and issuer material share the issuer origin.
    if kind == "issuer" or (official and (host == official or host.endswith("." + official))):
        return "issuer:" + profile["name"].casefold()
    if kind == "regulator" and (host.endswith(".gov.in") or host.endswith(".gov")):
        parts = host.split('.')
        agency = '.'.join(parts[-3:]) if host.endswith('.gov.in') else '.'.join(parts[-2:])
        return "regulator:" + agency
    # Unverified media/industry origin labels never establish independence automatically.
    return "unverified:" + (group or host)


def validate_future_test(test, as_of):
    if not test:
        raise ValueError("Future falsification test needs a metric, threshold, source and observation window.")
    start, end = date.fromisoformat(test["window_start"]), date.fromisoformat(test["window_end"])
    if start <= date.fromisoformat(as_of) or end <= start:
        raise ValueError("Falsification observation window must be in the future, after the investigation date.")
    try:
        threshold = Decimal(test["threshold"])
        if not threshold.is_finite():
            raise InvalidOperation
    except InvalidOperation:
        raise ValueError("Falsification threshold must be a finite number.") from None
    if not test["metric"].strip() or not test["source"].strip() or test["comparison"] not in {"above", "below", "at_least", "at_most"}:
        raise ValueError("Future falsification test lacks a measurable metric or expected source.")
    return (f"Reconsider if {test['metric']} is {test['comparison'].replace('_', ' ')} {test['threshold']} "
            f"during {start.isoformat()} to {end.isoformat()}, measured using {test['source']}. "
            "This is a proposed future test, not observed evidence.")


def validate_finding(draft, review, hypothesis, facts, sources, calculations, profile, as_of=None):
    valid_ids = set(facts)
    supporting = list(dict.fromkeys(draft["supporting_facts"]))
    opposing = list(dict.fromkeys(draft["opposing_facts"]))
    cited = supporting + opposing + draft["discovery"]["evidence"] + draft["counterargument"]["evidence"]
    cited += [fid for bullet in draft["why_it_matters"] for fid in bullet["evidence"]]
    cited += [fid for entry in draft["timeline"] for fid in entry["evidence"]]
    if any(fid not in valid_ids for fid in cited):
        raise ValueError("Finding cites unknown facts.")
    if not supporting or not draft["discovery"]["evidence"]:
        raise ValueError("Finding lacks supporting citations.")
    if not 3 <= len(draft["why_it_matters"]) <= 5:
        raise ValueError("Finding requires three to five significance bullets.")
    for claim in [draft["discovery"], draft["counterargument"], *draft["why_it_matters"]]:
        from .quality import scope_warning
        scope_problem = scope_warning(claim['text'], claim['evidence'], facts)
        if scope_problem:
            raise ValueError(scope_problem)
        if not claim["evidence"]:
            raise ValueError("Each claim needs source citations; present unsupported alternatives as limitations.")
        if any(cid not in calculations for cid in claim["calculations"]):
            raise ValueError("Claim cites an unknown calculation.")
        if any(not set(calculations[cid]["inputs"]) <= set(claim["evidence"]) for cid in claim["calculations"]):
            raise ValueError("Claim must cite the actual input facts of its financial calculation.")
        tokens = lambda text: [Decimal(t.replace(",", "")) for t in re.findall(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?", text)]
        grounded = [number for fid in claim["evidence"] for number in tokens(facts[fid]["quote"] + " " +
                    " ".join(a["quote"] for a in facts[fid].get("context_evidence", [])))]
        grounded += [Decimal(calculations[cid]["result"]) for cid in claim["calculations"]]
        for number in tokens(claim["text"]):
            # Permit displayed rounding, but not a number merely accompanied by an unrelated citation.
            places = max(0, -number.as_tuple().exponent)
            tolerance = Decimal(5) * (Decimal(10) ** (-places - 1))
            if not any(abs(abs(number) - abs(value)) <= tolerance for value in grounded):
                raise ValueError("Claim contains an ungrounded number.")
    for entry in draft["timeline"]:
        scope_problem = scope_warning(entry['description'], entry['evidence'], facts)
        if scope_problem:
            raise ValueError(scope_problem)
        if not entry["evidence"]:
            raise ValueError("Timeline event lacks evidence.")
        if re.fullmatch(r"FY\d{4}(?:-Q[1-4])?", entry["date"]):
            if not any(facts[fid]["fiscal_period"].upper().removeprefix('FY') == entry["date"].removeprefix('FY') for fid in entry["evidence"]):
                raise ValueError("Timeline fiscal period is not supported by a cited fact.")
        else:
            date.fromisoformat(entry["date"])
            if not any(facts[fid]["event_date"] == entry["date"] for fid in entry["evidence"]):
                raise ValueError("Timeline date is not supported by a dated cited fact.")
    # Unrelated supporting citations must not inflate corroboration of the discovery.
    source_ids = {facts[fid]["source_id"] for fid in draft["discovery"]["evidence"]}
    source_hashes = {sources[sid]["sha256"] for sid in source_ids}
    groups = {origin(sources[sid], profile) for sid in source_ids}
    verified = {g for g in groups if not g.startswith("unverified:")}
    independent = len(verified) >= 2 and len(source_hashes) >= 2
    problems = list(draft["limitations"])
    if not independent:
        problems.append("Independent corroboration is not established: publisher/domain count alone does not establish independent origin.")
    unresolved_tests = [t for t in review["alternative_tests"] if t["outcome"] != "ruled_out"]
    if unresolved_tests:
        problems.append("Alternative explanations remain: " + "; ".join(t["explanation"] for t in unresolved_tests))
    chronology = review["cause_precedes_effect"] and len(review["chronology_evidence"]) >= 2
    if review["causal_claim"]:
        dated = [facts[fid]["event_date"] for fid in review["chronology_evidence"] if fid in facts and facts[fid]["event_date"]]
        chronology = chronology and len(dated) >= 2 and dated[0] < dated[1]
        if not chronology:
            problems.append("Causal chronology is not established by distinct dated evidence.")
    status = "rejected" if review["verdict"] == "rejected" else draft["conclusion"]
    used_calcs = {cid for claim in [draft["discovery"], draft["counterargument"], *draft["why_it_matters"]] for cid in claim["calculations"]}
    if not draft["discovery"]["calculations"]:
        raise ValueError("Discovery lacks a cited validated financial calculation; scheduling facts alone are insufficient.")
    falsification = validate_future_test(review.get("future_test"), as_of or date.today().isoformat())
    if not draft["timeline"] and status == "supported":
        status = "unresolved"
        problems.append("No source-grounded timeline establishes when the financial story developed.")
    if not used_calcs and status == "supported":
        status = "unresolved"
        problems.append("No validated financial calculation establishes materiality.")
    if review["verdict"] == "unresolved" or not independent or (review["causal_claim"] and (not chronology or unresolved_tests)):
        if status != "rejected":
            status = "unresolved"
    if review["causal_claim"] and len(review["alternative_tests"]) < 2 and status == "supported":
        status = "unresolved"
        problems.append("Causal interpretation lacks at least two evidenced alternative-explanation tests.")
    strength = "Weak"
    if independent and status != "rejected":
        strength = "Moderate"
        if status == "supported" and not opposing and not unresolved_tests and (not review["causal_claim"] or chronology):
            strength = "Strong"
    rationale = (f"{len(source_ids)} cited source(s), {len(source_hashes)} distinct archived content hash(es), "
                 f"{len(verified)} conservatively verified origin group(s); "
                 f"{len(opposing)} opposing fact(s); {len(unresolved_tests)} unresolved/supported alternative(s). "
                 "Quotes and numbers are mechanically anchored; semantic support remains model-assessed.")
    return {"id": hypothesis["id"], "title": draft["discovery"]["text"], "claim": draft["discovery"]["text"],
            "status": status, "strength": strength, "strength_reason": rationale,
            "hypothesis": hypothesis["hypothesis"], "angle": hypothesis["angle"],
            "why_it_matters": draft["why_it_matters"], "discovery_evidence": draft["discovery"]["evidence"],
            "evidence": supporting, "opposing_evidence": opposing, "timeline": draft["timeline"],
            "calculations": [calculations[cid] for cid in sorted(used_calcs)],
            "counterarguments": [draft["counterargument"]["text"]], "counterargument_evidence": draft["counterargument"]["evidence"],
            "falsification": falsification, "future_test": review["future_test"], "next_steps": [t["explanation"] for t in unresolved_tests],
            "limitations": list(dict.fromkeys(problems)), "skeptic": review}
