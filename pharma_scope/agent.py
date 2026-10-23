"""Bounded autonomous research with LangGraph and SQLite stage checkpoints."""
from __future__ import annotations

from contextlib import nullcontext
from copy import deepcopy
from dataclasses import asdict, dataclass
import json
import os
import re
import time
from typing import TypedDict
from urllib.parse import urlparse

from jsonschema import validate

from . import schemas
from .evidence import calculation, extract_facts, validate_finding, anchored_identity
from .ingest import import_rows, norm
from .providers import Model, TransientModelError
from .store import digest, now, uid
from .webtools import WebTools, disclosure_score


class BudgetExceeded(ValueError):
    pass


@dataclass
class Limits:
    seconds: int = 600
    searches: int = 16
    sources: int = 18
    model_calls: int = 30
    rounds: int = 2
    hypotheses: int = 3
    pages_per_source: int = 10

    def validate(self):
        if any(not isinstance(v, int) or v < 1 for v in asdict(self).values()):
            raise ValueError("All research limits must be positive integers.")
        if self.rounds > 4 or self.hypotheses > 5 or self.pages_per_source > 20:
            raise ValueError("Maximum: 4 rounds, 5 hypotheses, 20 pages per source.")


class GraphState(TypedDict):
    payload: dict


class ResearchAgent:
    def __init__(self, store, model=None, web=None, limits=None, emit=None):
        self.store = store
        self.model = model or Model()
        self.web = web or WebTools()
        self.limits = limits or Limits()
        self.limits.validate()
        self.emit = emit
        self.started = 0
        self.base_elapsed = 0

    def remaining(self, state):
        remaining = self.limits.seconds - self.base_elapsed - (time.monotonic() - self.started)
        if remaining <= 0:
            raise BudgetExceeded("Research time budget exhausted. Completed stages and source evidence are saved.")
        return remaining

    def event(self, state, stage, message):
        entry = {"at": now(), "stage": stage, "message": message}
        state["events"].append(entry)
        if self.emit:
            self.emit(entry)

    def reserve(self, state, field):
        self.remaining(state)
        if state["usage"][field] >= getattr(self.limits, field):
            raise BudgetExceeded(f"{field} budget exhausted; resume with a larger explicit budget.")
        state["usage"][field] += 1
        # Persist reservations BEFORE external work so retries cannot hide consumption.
        self.store.checkpoint(state)

    def model_call(self, state, stage, task, schema, data):
        key = digest(json.dumps([state["id"], stage, getattr(self.model, "provider", "test"),
                                 getattr(self.model, "model", "test"), task, schema, data], sort_keys=True).encode())
        cached = self.store.cache(key)
        if cached is not None:
            state["usage"]["cache_hits"] += 1
            return cached
        for attempt in range(3):
            self.reserve(state, "model_calls")
            self.event(state, "model", f"Requesting {getattr(self.model, 'model', 'model')} for {stage} (attempt {attempt + 1}/3).")
            try:
                result = self.model.generate(task, schema, data, timeout=max(1, min(90, self.remaining(state))))
                break
            except TransientModelError as exc:
                delay = max(2 ** (attempt + 1), exc.retry_after)
                if attempt == 2 or delay > 30 or self.remaining(state) <= delay + 1:
                    raise
                self.event(state, "retry", f"{exc} Retrying in {delay:g} seconds.")
                self.store.checkpoint(state)
                time.sleep(delay)
        validate(result, schema)
        state["usage"]["model_usage"].append(getattr(self.model, "last_usage", {}))
        return self.store.cache(key, result)

    def search(self, state, query):
        key = digest(json.dumps([state["id"], "search", query]).encode())
        cached = self.store.cache(key)
        if cached is not None:
            state["usage"]["cache_hits"] += 1
            return cached
        if getattr(self.web, "provider", "") == "duckduckgo" and state.get("search_failure_streak", 0) >= 2:
            return []
        self.reserve(state, "searches")
        self.event(state, "search", f"Searching public sources: {query[:160]}")
        try:
            result = self.web.search(query, count=5, timeout=max(1, min(25, self.remaining(state))))
        except ValueError as exc:
            state["search_failure_streak"] = state.get("search_failure_streak", 0) + 1
            state["warnings"].append(f"Search unavailable for {query[:120]}: {exc}. Coverage is incomplete.")
            self.event(state, "search", "Search unavailable; continuing with other queries and readable archived sources.")
            return []
        state["search_failure_streak"] = 0
        return self.store.cache(key, result)

    def collect(self, state, results, limit=None, budget_reserve=0):
        added = 0
        for result in results:
            if state["usage"]["sources"] >= self.limits.sources - budget_reserve or (limit is not None and added >= limit):
                break
            url = result.get("url", "")
            if not url or url in state["attempted_urls"]:
                continue
            state["attempted_urls"].append(url)
            self.reserve(state, "sources")
            self.event(state, "collect", f"Downloading a source from {urlparse(url).hostname or 'unknown host'}.")
            try:
                sid = self.web.collect(self.store, state["company"], result, timeout=max(1, min(25, self.remaining(state))))
                if sid not in state["source_ids"]:
                    state["source_ids"].append(sid)
                    added += 1
            except (ValueError, OSError) as exc:
                state["warnings"].append(f"Could not collect {url}: {type(exc).__name__}: {str(exc)[:180]}")
        return added

    def sources(self, state):
        return [{**s, **self.store.metadata(s["id"])} for s in self.store.sources(state["company"]) if s["id"] in state["source_ids"]]

    def context(self, state):
        # Retain facts already used by hypotheses/reviews, then prefer fresh evidence.
        pinned = {fid for h in state["hypotheses"] for fid in h["supporting_facts"] + h["opposing_facts"]}
        pinned |= {fid for c in state["calculations"].values() for fid in c["inputs"]}
        pinned |= {fid for r in state["reviews"] for fid in r["supporting_facts"] + r["opposing_facts"] + r["chronology_evidence"]}
        chosen = [f for f in state["facts"] if f["id"] in pinned]
        size = len(json.dumps(chosen))
        for fact in reversed(state["facts"]):
            if fact["id"] in pinned:
                continue
            length = len(json.dumps(fact))
            if size + length > 100000:
                continue
            chosen.append(fact)
            size += length
        return {"company": state.get("profile", {}), "as_of": state["as_of"],
                "facts": chosen, "calculations": state["calculations"],
                "sources": [{k: v for k, v in s.items() if k not in {"pages", "search_lead"}} for s in self.sources(state)]}

    def resolve(self, state):
        results = self.search(state, state["company"] + " pharmaceutical company official investor relations annual report")
        self.collect(state, results, limit=3)
        sources = self.sources(state)
        if not sources:
            raise ValueError("No readable company sources collected; inspect retrieval warnings or try another search provider.")
        profile = self.model_call(state, "resolve", "Resolve the supplied company from fetched public evidence. "
            "Identity evidence quotes must be verbatim from the provided pages and URLs. Do not infer subsidiaries or facilities. "
            "Use uncertainty for unresolved identity. official_domain must be the issuer's bare domain (no scheme). "
            "Only name competitors supported by the provided text; empty lists are fine.", schemas.PROFILE,
            {"input": state["company"], "sources": [{"url": s["url"], "pages": [p[:18000] for p in s["pages"][:2]]} for s in sources]})
        profile = anchored_identity(profile, state["company"], sources)
        profile["index_eligibility"] = "Not established by identity resolution; research also supports listed companies outside NIFTY 50."
        state["profile"] = profile
        state["warnings"].extend(profile["uncertainty"])
        return "plan"

    def plan(self, state):
        result = self.model_call(state, "plan", "Choose research angles worth testing for this company across geography, business model and regulation. "
            "Return up to 3 ranked angles, each with 1-2 targeted search queries. Include annual/quarterly issuer filings and independent "
            "regulatory, industry or competitor evidence. Search for five fiscal years where relevant. No preset company thesis.",
            schemas.PLAN, {"profile": state["profile"], "as_of": state["as_of"], "years": state["years"]})
        state["plan"] = result
        return "gather"

    def gather(self, state):
        reserve = min(3, max(1, self.limits.sources // 4))
        self.follow_disclosures(state, max_new=5, budget_reserve=reserve)
        for angle in state["plan"]["angles"][:3]:
            for query in angle["queries"][:2]:
                if state["usage"]["searches"] >= self.limits.searches or state["usage"]["sources"] >= self.limits.sources - reserve:
                    break
                self.collect(state, sorted(self.search(state, query), key=disclosure_score, reverse=True), limit=2, budget_reserve=reserve)
        self.follow_disclosures(state, max_new=3, budget_reserve=reserve)
        return "extract"

    def follow_disclosures(self, state, max_new=5, budget_reserve=0):
        """Follow two bounded levels of official indexes before relying on more search calls."""
        if hasattr(self.web, "report_links"):
            initial = state["usage"]["sources"]
            for _ in range(2):
                room = min(max_new - (state["usage"]["sources"] - initial), self.limits.sources - state["usage"]["sources"] - budget_reserve)
                if room <= 0:
                    break
                links = self.web.report_links(self.store, self.sources(state), state["profile"].get("official_domain", ""))
                links = [r for r in links if r["url"] not in state["attempted_urls"]]
                if not links:
                    break
                self.collect(state, links[:room], limit=room, budget_reserve=budget_reserve)

    def recover_financial_evidence(self, state):
        if state.get("financial_recovery_attempted"):
            return False
        state["financial_recovery_attempted"] = True
        self.event(state, "gather", "Too little financial evidence; trying primary financial disclosures before forming hypotheses.")
        self.follow_disclosures(state, max_new=4)
        domain = state["profile"].get("official_domain", "")
        scope = ("site:" + domain + " ") if domain else ""
        for suffix in ["annual report consolidated financial statements filetype:pdf", "quarterly results revenue segment presentation filetype:pdf"]:
            if state["usage"]["searches"] >= self.limits.searches or state["usage"]["sources"] >= self.limits.sources:
                break
            leads = self.search(state, scope + state["profile"]["name"] + " " + suffix)
            self.collect(state, sorted(leads, key=disclosure_score, reverse=True), limit=2)
        return any(sid not in state["extracted"] for sid in state["source_ids"])

    def selected_pages(self, source):
        def score(text):
            patterns = [(r"geograph|reportable.segment|business.segment", 25),
                        (r"statement of profit and loss|statement of operations", 35),
                        (r"revenue from operations|revenue from contracts", 12),
                        (r"specialty|cdmo|formulations|warning letter|inspection|import alert|acquisition|constant.currency|margin", 3)]
            return sum(min(5, len(re.findall(p, text, re.I))) * weight for p, weight in patterns)
        ranked = sorted(enumerate(source["pages"], 1), key=lambda p: (-score(p[1]), p[0]))
        chosen = {}
        if source["pages"]:
            chosen[1] = source["pages"][0]
        # Reserve room for the actual income statement rather than mentions inside long notes.
        for p, text in enumerate(source["pages"], 1):
            if len(chosen) >= min(3, self.limits.pages_per_source):
                break
            if re.search(r"(?im)^\s*(?:consolidated\s+)?statement of (?:profit and loss|operations)\s*$", text):
                chosen[p] = text
        for p, text in ranked:
            if len(chosen) >= self.limits.pages_per_source:
                break
            chosen.setdefault(p, text)
        return [{"page": p, "text": text[:12000]} for p, text in sorted(chosen.items())]

    def extract(self, state):
        existing = {f["id"] for f in state["facts"]}
        ordered_sources = sorted(self.sources(state), key=lambda s: (not str(s.get('original_archive', s.get('archived', ''))).lower().endswith('.pdf'),
                                  -disclosure_score({'url': s['url'], 'title': s['title']})[0]))
        for source in ordered_sources:
            if source["id"] in state["extracted"]:
                continue
            numeric_count = sum(f['kind'] == 'financial' and bool(f['value']) for f in state['facts'])
            reserved_calls = min(6, self.limits.model_calls // 3)
            if numeric_count >= 2 and (state['usage']['model_calls'] >= self.limits.model_calls - reserved_calls or
                                       self.remaining(state) <= min(120, self.limits.seconds / 3)):
                state['warnings'].append('Document extraction stopped to reserve budget for hypothesis testing and review; some collected documents remain unextracted.')
                self.event(state, 'extract', 'Reserving the remaining analysis budget; unprocessed documents remain in the source inventory.')
                break
            if hasattr(self.web, 'is_report_index') and self.web.is_report_index(self.store, source):
                self.event(state, 'extract', 'Report directory retained for provenance; extracting its linked documents instead.')
                state['extracted'].append(source['id'])
                continue
            if source["published"] and source["published"] > state["as_of"]:
                state["warnings"].append(f"{source['id']}: publication date is after the investigation date; source excluded.")
                state["extracted"].append(source["id"])
                continue
            result = self.model_call(state, "extract:" + source["id"],
                "Extract up to 16 relevant source facts for financial discovery, including contradictions, reporting changes and dated events. "
                "Every fact quote must be verbatim on its cited physical page. statement must be fully supported by quote. "
                "For numeric facts, give the original number as decimal text without commas, metric, fiscal_period, currency, original unit, "
                "Use the SAME metric and definition labels for comparable measurements across periods. definition describes the "
                "measurement meaning (e.g. revenue from operations), NOT the year, amount or date; those belong in fiscal_period/value. "
                "basis and definition. fiscal_period must use FY2025 or FY2025-Q1, where the year is the fiscal END year. "
                "Units: units/thousand/lakh/million/crore/billion/%/percent/days/ratio. "
                "For nonnumeric facts use empty strings for unavailable fields. Dates YYYY-MM-DD only when explicitly stated; otherwise empty. "
                "origin_group names the ORIGINAL issuer/regulator/research origin, not a republisher. Mark company press releases as issuer even on news sites. "
                "geography_observations is optional (empty if unclear); use Total for matching consolidated geographic revenue totals. "
                "Do not infer missing values, units or periods. The main quote must be a contiguous verbatim table row or passage. "
                "Use context_evidence [{page,quote}] for SEPARATE verbatim table headers, units, reporting basis and period labels. "
                "Context must be on the same or adjacent page (document-wide basis can cite page 1). Never stitch separate cells into a sentence. "
                "For multiple columns explicitly associate each original number with its actual column header. "
                "Extract numeric values, not just earnings schedules; return empty facts when the document has no substantive business evidence.",
                schemas.FACTS, {"company": state["profile"], "source_id": source["id"], "url": source["url"],
                                "title": source["title"], "pages": self.selected_pages(source)})
            facts, errors = extract_facts(source, result["facts"])
            if errors:
                original_facts = facts
                repair_data = {"company": state["profile"], "source_id": source["id"], "url": source["url"],
                               "title": source["title"], "pages": self.selected_pages(source), "validation_errors": errors,
                               "previous_output": result}
                result = self.model_call(state, "repair-extraction:" + source["id"],
                    "The previous extraction failed source validation. Extract again conservatively from the supplied pages. "
                    "Every quote must be ONE contiguous verbatim passage, preserving words and numbers; do not stitch table cells "
                    "or nonadjacent lines into an invented sentence. Whitespace may differ. event_date must be empty unless "
                    "the full day, month and year occur explicitly INSIDE that quote. A fiscal quarter does not prove an exact event date. "
                    "Put separate table headers, units and period labels in context_evidence with their own page and verbatim quote. "
                    "Each context quote must itself be contiguous: do not join a header directly to a distant table row. "
                    "Unit labels must use lowercase units/thousand/lakh/million/crore/billion/%/percent/days/ratio. "
                    "definition must describe the measurement without year/date; use the same metric/basis/definition for comparable periods. "
                    "Do not require the year and number in one passage when separate cited headers supply the year. "
                    "For numeric facts, include year, metric, value, original unit, currency, reporting basis and definition only "
                    "when known. If reporting context is unclear, retain a qualitative source fact with value and unavailable fields empty; "
                    "never assume a missing basis or calculate a missing value. Prefer fewer verifiable facts over broad coverage. "
                    "Source classification and geographic observations follow the same conservative rules; empty observations are fine.",
                    schemas.FACTS, repair_data)
                facts, errors = extract_facts(source, result["facts"])
                facts = list({f["id"]: f for f in original_facts + facts}.values())
            historical = [f for f in facts if not f["event_date"] or f["event_date"] <= state["as_of"]]
            if len(historical) != len(facts):
                state["warnings"].append(f"{source['id']}: future-dated events excluded from historical evidence.")
            facts = historical
            state["facts"].extend(f for f in facts if f["id"] not in existing)
            existing.update(f["id"] for f in facts)
            state["warnings"].extend(f"{source['id']}: rejected fact: {e}" for e in errors)
            for row in result["geography_observations"]:
                try:
                    import_rows(self.store, [{**row, "source_id": source["id"]}])
                except ValueError as exc:
                    state["warnings"].append(f"{source['id']}: geographic extraction rejected: {exc}")
            metadata = self.store.metadata(source["id"])
            self.store.metadata(source["id"], {**metadata, "source_kind": result["source_kind"],
                "origin_group": result["origin_group"], "model_publication_date": result["publication_date"]})
            state["extracted"].append(source["id"])
            self.store.checkpoint(state)
        numeric = [f for f in state["facts"] if f["value"] and f["kind"] == "financial"]
        if len(numeric) < 2 and not state["hypotheses"]:
            if self.recover_financial_evidence(state):
                return "extract"
            state["warnings"].append("Insufficient financial evidence to form a hypothesis: at least two anchored financial numbers are required. Scheduling notices do not establish a financial discovery.")
            return "compose"
        return "hypothesize" if not state["hypotheses"] else "skeptic"

    def hypothesize(self, state):
        result = self.model_call(state, "hypothesize", "Propose up to 3 non-obvious, financially meaningful hypotheses based only on facts. "
            "Cite existing fact IDs. Design tests that could disprove each. Propose up to 3 supporting AND opposing search queries each. "
            "Request calculations using exactly two numeric fact IDs: share/margin_pct = first/second*100 (same fiscal period); "
            "growth_pct=(second/first-1)*100 (same metric across periods); difference=second-first; cagr_pct uses a verified year interval. "
            "Use globally unique calculation IDs and do not reuse IDs. Prefer hypotheses with a measurable financial relationship. "
            "Every hypothesis MUST cite two numeric financial facts and request at least one valid calculation on its supporting facts. "
            "An earnings date or call schedule is not a business-model shift, financial effect, or trading-volatility measurement. "
            "Do not propose price/volume/institutional-trading relationships without actual price/volume/ownership evidence. "
            "A hypothesis is not a conclusion; do not present unsupported causes as established facts. Return no hypotheses if inadequate.", schemas.HYPOTHESES, self.context(state))
        known = {f["id"] for f in state["facts"]}
        financial_ids = {f["id"] for f in state["facts"] if f["kind"] == "financial" and f["value"]}
        for index, h in enumerate(result["hypotheses"][:self.limits.hypotheses], 1):
            if not h["supporting_facts"] or any(fid not in known for fid in h["supporting_facts"] + h["opposing_facts"]):
                state["warnings"].append("Rejected hypothesis with missing or invented fact IDs.")
                continue
            if len(financial_ids.intersection(h["supporting_facts"])) < 2:
                state["warnings"].append("Withheld hypothesis: its supporting evidence lacks two numeric financial facts.")
                continue
            h["id"] = "hypothesis-" + str(index)
            valid_calcs = {}
            for spec in h["calculations"]:
                try:
                    if spec["id"] in state["calculations"] or spec["id"] in valid_calcs:
                        raise ValueError("Duplicate calculation ID.")
                    if not set(spec["inputs"]) <= set(h["supporting_facts"]):
                        raise ValueError("Calculation inputs are not part of the hypothesis supporting evidence.")
                    valid_calcs[spec["id"]] = calculation(spec, {f["id"]: f for f in state["facts"]})
                except ValueError as exc:
                    state["warnings"].append(f"Rejected calculation: {exc}")
            if not valid_calcs:
                state["warnings"].append("Withheld hypothesis: no validated calculation establishes its financial basis.")
                continue
            state["calculations"].update(valid_calcs)
            state["hypotheses"].append(h)
        state["pending_queries"] = [q for h in state["hypotheses"] for q in h["followup_queries"][:3]]
        return "followup" if state["hypotheses"] else "compose"

    def followup(self, state):
        state["round"] += 1
        for query in state["pending_queries"][:4]:
            if state["usage"]["searches"] >= self.limits.searches or state["usage"]["sources"] >= self.limits.sources:
                state["warnings"].append("Supporting/opposing research stopped at the configured search/source budget.")
                break
            self.collect(state, self.search(state, query), limit=1)
        return "extract"

    def skeptic(self, state):
        result = self.model_call(state, "skeptic:" + str(state["round"]),
            "Independently challenge every hypothesis. Verify supporting and opposing fact IDs. Explicitly test FX, acquisitions, "
            "reclassification, sector-wide trends and entity/facility mismatches where relevant. Tests lacking evidence MUST be unresolved. "
            "For causal claims chronology_evidence must list the cause fact first, effect fact second, each explicitly dated. "
            "A financial cause needs a measurable financial effect, not only management commentary. Explain the strongest counterargument. "
            "Return targeted searches for remaining contradictions. Falsification must specify measurable FUTURE evidence and a time window. "
            "future_test must give metric (including unit), comparison, numeric threshold, window_start and window_end YYYY-MM-DD, "
            "and expected public source. window_start MUST be AFTER the supplied as_of date, never a historical event date. "
            "Verdict supported only when multiple independent origins support the interpretation and important alternatives were tested; "
            "otherwise unresolved or rejected. Do not treat absence of retrieved evidence as disproof.", schemas.SKEPTIC,
            {**self.context(state), "hypotheses": state["hypotheses"]})
        known = {f["id"] for f in state["facts"]}
        hypotheses = {h["id"] for h in state["hypotheses"]}
        reviews = []
        for review in result["reviews"]:
            cited = review["supporting_facts"] + review["opposing_facts"] + review["chronology_evidence"]
            cited += [fid for t in review["alternative_tests"] for fid in t["evidence"]]
            if review["hypothesis_id"] in hypotheses and all(fid in known for fid in cited):
                for test in review["alternative_tests"]:
                    if not test["evidence"]:
                        test["outcome"] = "unresolved"
                reviews.append(review)
            else:
                state["warnings"].append("Rejected skeptic review with unknown hypothesis or evidence IDs.")
        state["reviews"] = reviews
        state["pending_queries"] = [q for r in reviews for q in r["followup_queries"][:2]]
        if state["round"] < self.limits.rounds and state["pending_queries"] and state["usage"]["sources"] < self.limits.sources and state["usage"]["searches"] < self.limits.searches:
            return "followup"
        return "compose"

    def compose(self, state):
        if not state["hypotheses"] or not state["reviews"]:
            state["findings"] = []
            state["warnings"].append("Insufficient evidence to publish a reviewed discovery.")
            return "publish"
        result = self.model_call(state, "compose", "Produce findings using the reviewed evidence, with all eight required elements. "
            "Each discovery, each of 3-5 significance bullets and the counterargument must cite existing fact IDs; numeric derived claims "
            "must also cite the supplied calculation ID. Cite only valid provided calculation results; do not calculate independently. "
            "Timeline date can be YYYY-MM-DD matching a cited fact's event_date OR FY2025/FY2025-Q1 matching a cited fiscal_period. "
            "Use fiscal labels for financial developments; never convert a quarter or fiscal year to an invented exact calendar date. "
            "Include evidence for and against. Do not upgrade unresolved or rejected hypotheses. Phrase unresolved findings as tentative "
            "interpretations with the observed facts distinguished. Falsification conditions must specify future measurable observations. "
            "Report unsupported alternative explanations as limitations, not facts. Do not publish claims unsupported by passages.",
            schemas.FINDINGS, {**self.context(state), "hypotheses": state["hypotheses"], "reviews": state["reviews"]})
        audit = self.model_call(state, "audit-claims", "Audit EACH draft conservatively against quoted source facts and supplied calculations. "
            "Check discovery, significance bullets, counterargument, and the underlying hypothesis. Citations alone do not establish support. "
            "Every asserted variable and relationship needs evidence: scheduled calls do not establish volatility, institutional trading, "
            "or business-model changes. A calculation unrelated to the claim is not support. Tentative wording does not excuse invention. "
            "Check actual column/period/unit associations using context_evidence. Separate an explicitly tentative causal test from an "
            "asserted correlation without measured effect. Mark all_claims_supported false if any core assertion goes beyond the passages; "
            "list unsupported_claims. Mark track_relevant only for substantive geographic, business-model or regulatory financial research. "
            "This is a second model review, not a guarantee of truth.", schemas.CLAIM_AUDIT,
            {**self.context(state), "drafts": result["findings"], "hypotheses": state["hypotheses"]})
        audits = {r["hypothesis_id"]: r for r in audit["reviews"]}
        hypotheses = {h["id"]: h for h in state["hypotheses"]}
        reviews = {r["hypothesis_id"]: r for r in state["reviews"]}
        facts = {f["id"]: f for f in state["facts"]}
        sources = {s["id"]: s for s in self.sources(state)}
        accepted = set()
        for draft in result["findings"]:
            hid = draft["hypothesis_id"]
            if hid not in hypotheses or hid not in reviews or hid in accepted:
                continue
            checked = audits.get(hid)
            if not checked or not checked["all_claims_supported"] or not checked["track_relevant"] or checked["unsupported_claims"]:
                state["warnings"].append(f"Withheld finding {hid}: claim-support audit failed; " + ("; ".join(checked["unsupported_claims"]) if checked else "no audit returned"))
                continue
            try:
                finding = validate_finding(draft, reviews[hid], hypotheses[hid], facts, sources, state["calculations"], state["profile"], state["as_of"])
                finding["claim_audit"] = checked
                # An unresolved explanation cannot be headlined as a proven discovery.
                if finding["status"] != "supported":
                    finding["title"] = finding["status"].capitalize() + " hypothesis: " + draft["discovery"]["text"]
                    finding["claim"] = finding["title"]
                state["findings"].append(finding)
                accepted.add(hid)
            except (ValueError, KeyError) as exc:
                state["warnings"].append(f"Withheld finding {hid}: {exc}")
        return "publish"

    def publish(self, state):
        state["status"] = "completed" if any(f["status"] == "supported" for f in state["findings"]) else "insufficient_evidence"
        return "done"

    def snapshot(self, state):
        return {"id": state["id"], "kind": "research", "company": state["company"], "created": state["created"],
                "status": state["status"], "demo": False, "engine": "LangGraph hypothesis-evidence-contradiction investigation",
                "profile": state.get("profile", {}), "plan": state.get("plan", {}), "parameters": state["limits"], "as_of": state["as_of"],
                "usage": state["usage"], "events": state["events"], "findings": state["findings"], "warnings": state["warnings"],
                "facts": state["facts"], "observations": self.store.observations(state["company"]), "sources": self.sources(state),
                "hypotheses": state["hypotheses"], "reviews": state["reviews"], "calculations": state["calculations"]}

    def run(self, company=None, years=5, as_of=None, resume=None):
        from langgraph.graph import END, START, StateGraph
        if resume:
            state = self.store.agent_state(resume)
            state["search_failure_streak"] = 0
            if state["next_stage"] == "extract" and not state["facts"]:
                state["extracted"] = []
            state["limits"] = asdict(self.limits)
            if state["next_stage"] == "done":
                return self.snapshot(state)
        else:
            if not company or not company.strip() or years < 2:
                raise ValueError("A company and at least two research years are required.")
            state = {"id": uid("run"), "company": company.strip().upper(), "created": now(), "as_of": as_of or now()[:10],
                "years": years, "limits": asdict(self.limits), "status": "running", "next_stage": "resolve", "elapsed": 0,
                "usage": {"searches": 0, "sources": 0, "model_calls": 0, "cache_hits": 0, "model_usage": []},
                "events": [], "warnings": [], "source_ids": [], "attempted_urls": [], "facts": [], "extracted": [],
                "hypotheses": [], "reviews": [], "calculations": {}, "findings": [], "round": 0, "pending_queries": []}
            state["warnings"].append("Source-origin classification and semantic support are model-assessed; mechanically valid citations do not prove causation.")
            state["warnings"].append("Publication dates may be unknown. This is current public-source research, not a point-in-time backtest.")
        self.web.ready()
        self.started, self.base_elapsed = time.monotonic(), state["elapsed"]
        state["status"] = "running"
        self.store.checkpoint(state)
        self.store.save_run(self.snapshot(state))
        stages = ["resolve", "plan", "gather", "extract", "hypothesize", "followup", "skeptic", "compose", "publish"]
        graph = StateGraph(GraphState)

        def execute(stage):
            def node(wrapped):
                current = deepcopy(wrapped["payload"])
                try:
                    self.remaining(current)
                    self.event(current, stage, f"Starting {stage}.")
                    next_stage = getattr(self, stage)(current)
                    current["next_stage"] = next_stage
                    current["elapsed"] = self.base_elapsed + time.monotonic() - self.started
                    self.event(current, stage, f"Completed {stage}; {len(current['source_ids'])} sources, {len(current['facts'])} anchored facts, {len(current['findings'])} finding(s).")
                    self.store.checkpoint(current)
                    self.store.save_run(self.snapshot(current))
                    return {"payload": current}
                except (Exception, KeyboardInterrupt) as exc:
                    current["status"] = "interrupted" if isinstance(exc, KeyboardInterrupt) else "budget_exhausted" if isinstance(exc, BudgetExceeded) else "failed"
                    current["elapsed"] = self.base_elapsed + time.monotonic() - self.started
                    self.event(current, stage, f"Stopped at {stage}: {type(exc).__name__}. Evidence and checkpoint retained.")
                    self.store.checkpoint(current)
                    self.store.save_run(self.snapshot(current))
                    raise
            return node

        routes = {name: name for name in stages} | {"done": END}
        graph.add_conditional_edges(START, lambda s: s["payload"]["next_stage"], routes)
        for stage in stages:
            graph.add_node(stage, execute(stage))
            graph.add_conditional_edges(stage, lambda s: s["payload"]["next_stage"], routes)
        compiled = graph.compile()
        tracing = os.getenv("LANGSMITH_TRACING", "").lower() == "true"
        if tracing and not os.getenv("LANGSMITH_API_KEY"):
            raise ValueError("LANGSMITH_TRACING=true requires LANGSMITH_API_KEY; otherwise disable tracing.")
        if tracing:
            from langsmith import trace
            context = trace("PHARMA-SCOPE research", inputs={"company": state["company"], "run_id": state["id"]})
        else:
            context = nullcontext()
        with context:
            final = compiled.invoke({"payload": state}, config={"recursion_limit": 60, "run_name": "PHARMA-SCOPE"})
        return self.snapshot(final["payload"])
