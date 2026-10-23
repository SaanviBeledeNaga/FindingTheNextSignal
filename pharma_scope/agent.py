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
from .webtools import WebTools


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

    def collect(self, state, results, limit=None):
        added = 0
        for result in results:
            if state["usage"]["sources"] >= self.limits.sources or (limit is not None and added >= limit):
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
        for angle in state["plan"]["angles"][:3]:
            for query in angle["queries"][:2]:
                self.collect(state, self.search(state, query), limit=2)
        # Official report indexes often link directly to PDFs even when search is unavailable.
        if hasattr(self.web, "report_links"):
            links = self.web.report_links(self.store, self.sources(state), state["profile"].get("official_domain", ""))
            self.collect(state, links, limit=3)
        return "extract"

    def selected_pages(self, source):
        words = r"geograph|segment|specialty|cdmo|formulations|revenue|warning letter|inspection|import alert|acquisition|constant.currency|margin"
        ranked = sorted(enumerate(source["pages"], 1), key=lambda p: (-len(re.findall(words, p[1], re.I)), p[0]))
        return [{"page": p, "text": text[:9000]} for p, text in sorted(ranked[:self.limits.pages_per_source])]

    def extract(self, state):
        existing = {f["id"] for f in state["facts"]}
        for source in self.sources(state):
            if source["id"] in state["extracted"]:
                continue
            if source["published"] and source["published"] > state["as_of"]:
                state["warnings"].append(f"{source['id']}: publication date is after the investigation date; source excluded.")
                state["extracted"].append(source["id"])
                continue
            result = self.model_call(state, "extract:" + source["id"],
                "Extract up to 16 relevant source facts for financial discovery, including contradictions, reporting changes and dated events. "
                "Every fact quote must be verbatim on its cited physical page. statement must be fully supported by quote. "
                "For numeric facts, give the original number as decimal text without commas, metric, fiscal_period, currency, original unit, "
                "basis and definition. Units: units/thousand/lakh/million/crore/billion/%/percent/days/ratio. "
                "For nonnumeric facts use empty strings for unavailable fields. Dates YYYY-MM-DD only when explicitly stated; otherwise empty. "
                "origin_group names the ORIGINAL issuer/regulator/research origin, not a republisher. Mark company press releases as issuer even on news sites. "
                "geography_observations is optional (empty if unclear); use Total for matching consolidated geographic revenue totals. "
                "Do not infer missing values, units or periods. Include complete table header context inside quotes when needed.",
                schemas.FACTS, {"company": state["profile"], "source_id": source["id"], "url": source["url"],
                                "title": source["title"], "pages": self.selected_pages(source)})
            facts, errors = extract_facts(source, result["facts"])
            if errors and not facts:
                repair_data = {"company": state["profile"], "source_id": source["id"], "url": source["url"],
                               "title": source["title"], "pages": self.selected_pages(source), "validation_errors": errors}
                result = self.model_call(state, "repair-extraction:" + source["id"],
                    "The previous extraction failed source validation. Extract again conservatively from the supplied pages. "
                    "Every quote must be ONE contiguous verbatim passage, preserving words and numbers; do not stitch table cells "
                    "or nonadjacent lines into an invented sentence. Whitespace may differ. event_date must be empty unless "
                    "the full day, month and year occur explicitly INSIDE that quote. A fiscal quarter does not prove an exact event date. "
                    "For numeric facts, include year, metric, value, original unit, currency, reporting basis and definition only "
                    "when known. If reporting context is unclear, retain a qualitative source fact with value and unavailable fields empty; "
                    "never assume a missing basis or calculate a missing value. Prefer fewer verifiable facts over broad coverage. "
                    "Source classification and geographic observations follow the same conservative rules; empty observations are fine.",
                    schemas.FACTS, repair_data)
                facts, errors = extract_facts(source, result["facts"])
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
        if not state["facts"]:
            state["warnings"].append("No source-anchored facts passed validation; evidence is insufficient for hypotheses.")
            return "compose"
        return "hypothesize" if not state["hypotheses"] else "skeptic"

    def hypothesize(self, state):
        result = self.model_call(state, "hypothesize", "Propose up to 3 non-obvious, financially meaningful hypotheses based only on facts. "
            "Cite existing fact IDs. Design tests that could disprove each. Propose up to 3 supporting AND opposing search queries each. "
            "Request calculations using exactly two numeric fact IDs: share/margin_pct = first/second*100 (same fiscal period); "
            "growth_pct=(second/first-1)*100 (same metric across periods); difference=second-first; cagr_pct uses a verified year interval. "
            "Use globally unique calculation IDs and do not reuse IDs. Prefer hypotheses with a measurable financial relationship. "
            "A hypothesis is not a conclusion; do not present unsupported causes as established facts.", schemas.HYPOTHESES, self.context(state))
        known = {f["id"] for f in state["facts"]}
        for index, h in enumerate(result["hypotheses"][:self.limits.hypotheses], 1):
            if not h["supporting_facts"] or any(fid not in known for fid in h["supporting_facts"] + h["opposing_facts"]):
                state["warnings"].append("Rejected hypothesis with missing or invented fact IDs.")
                continue
            h["id"] = "hypothesis-" + str(index)
            state["hypotheses"].append(h)
            for spec in h["calculations"]:
                try:
                    if spec["id"] in state["calculations"]:
                        raise ValueError("Duplicate calculation ID.")
                    state["calculations"][spec["id"]] = calculation(spec, {f["id"]: f for f in state["facts"]})
                except ValueError as exc:
                    state["warnings"].append(f"Rejected calculation: {exc}")
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
            "Supply a dated timeline supported by the event_date fields of cited facts; omit undated events instead of inventing dates. "
            "Include evidence for and against. Do not upgrade unresolved or rejected hypotheses. Phrase unresolved findings as tentative "
            "interpretations with the observed facts distinguished. Falsification conditions must specify future measurable observations. "
            "Report unsupported alternative explanations as limitations, not facts. Do not publish claims unsupported by passages.",
            schemas.FINDINGS, {**self.context(state), "hypotheses": state["hypotheses"], "reviews": state["reviews"]})
        hypotheses = {h["id"]: h for h in state["hypotheses"]}
        reviews = {r["hypothesis_id"]: r for r in state["reviews"]}
        facts = {f["id"]: f for f in state["facts"]}
        sources = {s["id"]: s for s in self.sources(state)}
        accepted = set()
        for draft in result["findings"]:
            hid = draft["hypothesis_id"]
            if hid not in hypotheses or hid not in reviews or hid in accepted:
                continue
            try:
                finding = validate_finding(draft, reviews[hid], hypotheses[hid], facts, sources, state["calculations"], state["profile"])
                # An unresolved explanation cannot be headlined as a proven discovery.
                if finding["status"] != "supported":
                    finding["title"] = finding["status"].capitalize() + " hypothesis: " + hypotheses[hid]["hypothesis"]
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
                "profile": state.get("profile", {}), "plan": state.get("plan", {}), "parameters": state["limits"],
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
                except Exception as exc:
                    current["status"] = "budget_exhausted" if isinstance(exc, BudgetExceeded) else "failed"
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
