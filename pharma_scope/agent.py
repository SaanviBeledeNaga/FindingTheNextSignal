"""Bounded autonomous research with LangGraph and SQLite stage checkpoints."""
from __future__ import annotations

from contextlib import nullcontext
from copy import deepcopy, copy
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from dataclasses import asdict, dataclass
import json
import os
import re
import time
from typing import TypedDict
from urllib.parse import urlparse

from jsonschema import validate

from . import schemas
from .evidence import calculation, extract_facts, validate_finding, anchored_identity, company_financial_facts, IdentityResolutionError, identity_matches
from .ingest import import_rows, norm
from .providers import Model, TransientModelError
from .store import digest, now, uid
from .webtools import WebTools, disclosure_score, document_year, NON_ISSUER_DOMAINS, host_is
from .research_policy import VERSION, current_facts, period_allowed, source_issue, section_scope, publication_view


class BudgetExceeded(ValueError):
    pass


class ResearchPaused(ValueError):
    pass


@dataclass
class Limits:
    seconds: int = 270
    searches: int = 16
    sources: int = 18
    model_calls: int = 30
    rounds: int = 2
    hypotheses: int = 3
    pages_per_source: int = 10
    fast_mode: bool = False

    def validate(self):
        if any(not isinstance(v, int) or v < 1 for k, v in asdict(self).items() if k != 'fast_mode'):
            raise ValueError("All research limits must be positive integers.")
        if not isinstance(self.fast_mode, bool):
            raise ValueError('fast_mode must be a boolean.')
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
        self.cancel = None
        self.prefetch_failures = set()
        self.source_cache = {}

    def cache_key(self, state, stage, task, schema, data):
        return digest(json.dumps([state['id'], stage, getattr(self.model, 'provider', 'test'),
                                  getattr(self.model, 'model', 'test'), task, schema, data], sort_keys=True).encode())

    def finish_reserve(self, state):
        # These calls remain mandatory: hypothesis, skeptic, composition and claim audit.
        return 85 if not state['hypotheses'] else 65

    def remaining(self, state):
        if self.cancel and self.cancel():
            raise ResearchPaused('Research paused by the user. The saved checkpoint can be continued.')
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
        key = self.cache_key(state, stage, task, schema, data)
        cached = self.store.cache(key)
        if cached is not None:
            state["usage"]["cache_hits"] += 1
            return cached
        for attempt in range(3):
            self.reserve(state, "model_calls")
            timeout = min(25 if self.limits.fast_mode else 90, self.remaining(state))
            self.event(state, "model", f"Requesting {getattr(self.model, 'model', 'model')} for {stage} (attempt {attempt + 1}/{2 if self.limits.fast_mode else 3}; deadline {timeout:.1f}s).")
            try:
                generate = getattr(self.model, 'generate_bounded', self.model.generate)
                result = generate(task, schema, data, timeout=timeout)
                break
            except TransientModelError as exc:
                delay = max(2 ** (attempt + 1), exc.retry_after)
                if attempt == (1 if self.limits.fast_mode else 2) or delay > 30 or self.remaining(state) <= delay + self.finish_reserve(state):
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
            result = self.web.search(query, count=5, timeout=max(1, min(8 if self.limits.fast_mode else 25, self.remaining(state))))
        except ValueError as exc:
            state["search_failure_streak"] = state.get("search_failure_streak", 0) + 1
            state["warnings"].append(f"Search unavailable for {query[:120]}: {exc}. Coverage is incomplete.")
            self.event(state, "search", "Search unavailable; continuing with other queries and readable archived sources.")
            return []
        state["search_failure_streak"] = 0
        return self.store.cache(key, result)

    def collect(self, state, results, limit=None, budget_reserve=0):
        if self.limits.fast_mode and hasattr(self.web, 'collect_downloaded'):
            return self.collect_parallel(state, results, limit, budget_reserve)
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
                sid = self.web.collect(self.store, state["company"], result, timeout=max(1, min(8 if self.limits.fast_mode else 25, self.remaining(state))))
                if sid not in state["source_ids"]:
                    state["source_ids"].append(sid)
                    added += 1
            except (ValueError, OSError) as exc:
                state["warnings"].append(f"Could not collect {url}: {type(exc).__name__}: {str(exc)[:180]}")
        return added

    def collect_parallel(self, state, results, limit=None, budget_reserve=0):
        """Only network work runs concurrently; all archive/SQLite writes stay here."""
        room = max(0, self.limits.sources - budget_reserve - state['usage']['sources'])
        room = min(room, limit if limit is not None else room)
        selected, seen = [], set(state['attempted_urls'])
        for result in results:
            url = result.get('url')
            if url and url not in seen and len(selected) < room:
                selected.append(result)
                seen.add(url)
        if not selected:
            return 0
        pool = ThreadPoolExecutor(max_workers=3)
        futures, added = {}, 0
        try:
            for result in selected:
                if self.remaining(state) <= self.finish_reserve(state) + 10:
                    break
                state['attempted_urls'].append(result['url'])
                self.reserve(state, 'sources')
                self.event(state, 'collect', 'Fetching public document: ' + (urlparse(result['url']).hostname or 'unknown'))
                futures[pool.submit(self.web.download, result['url'], min(12, self.remaining(state)))] = result
            while futures:
                self.remaining(state)
                done, _ = wait(futures, timeout=.2, return_when=FIRST_COMPLETED)
                for future in done:
                    result = futures.pop(future)
                    try:
                        downloaded = future.result()
                        sid = self.web.collect_downloaded(self.store, state['company'], result, downloaded,
                                                          parse_timeout=min(12, max(1,self.remaining(state)-self.finish_reserve(state))))
                        if sid not in state['source_ids']:
                            state['source_ids'].append(sid)
                            added += 1
                    except (ValueError, OSError) as exc:
                        state['warnings'].append(f"Could not collect {result['url']}: {type(exc).__name__}: {str(exc)[:180]}")
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        return added

    def sources(self, state):
        ids = set(state['source_ids'])
        if not ids <= self.source_cache.keys():
            self.source_cache.update({s['id']:s for s in self.store.sources(state['company']) if s['id'] in ids})
        return [{**self.source_cache[sid], **self.store.metadata(sid)} for sid in state['source_ids'] if sid in self.source_cache]

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
        results = self.search(state, state["company"] + " official investor relations annual report financial statements")
        self.collect(state, results, limit=3)
        sources = self.sources(state)
        if not sources and self.limits.fast_mode:
            # JavaScript investor pages can be unreadable. Try full disclosures
            # and report catalogs before abandoning source-grounded identity.
            for suffix in ['annual report consolidated financial statements filetype:pdf', 'annual report site:annualreports.com']:
                if self.remaining(state) <= 180 or state['usage']['searches'] >= self.limits.searches:
                    break
                self.collect(state, sorted(self.search(state,state['company'] + ' ' + suffix),key=disclosure_score,reverse=True),limit=2)
                sources = self.sources(state)
                if sources:
                    break
        if not sources:
            raise ValueError("No readable company sources collected; inspect retrieval warnings or try another search provider.")
        profile = self.model_call(state, "resolve", "Resolve the supplied company from fetched public evidence. "
            "Identity evidence quotes must be verbatim from the provided pages and URLs. Do not infer subsidiaries or facilities. "
            "Use uncertainty for unresolved identity. official_domain must be the issuer's bare domain (no scheme). "
            "Only name competitors supported by the provided text; empty lists are fine.", schemas.PROFILE,
            {"input": state["company"], "sources": [{"url": s["url"], "pages": [p[:18000] for p in s["pages"][:2]]} for s in sources]})
        try:
            profile = anchored_identity(profile, state["company"], sources)
        except IdentityResolutionError as exc:
            if not self.can_repair(state):
                raise
            self.event(state, 'resolve', 'Identity quote validation failed; checking one source-grounded repair.')
            profile = self.model_call(state, 'repair-identity',
                'Repair the company identity using only supplied source pages. Address validation_error. '
                'Copy ONE contiguous company-name passage exactly, preserving original punctuation and source URL. '
                'Do not stitch text or invent a ticker, name, subsidiary or facility. Leave unknown fields empty. '
                'Use uncertainty for unsupported details.', schemas.PROFILE,
                {'input':state['company'], 'previous_output':profile, 'validation_error':str(exc),
                 'sources':[{'url':s['url'],'pages':[p[:18000] for p in s['pages'][:2]]} for s in sources]})
            profile = anchored_identity(profile, state['company'], sources)
        from .eligibility import check
        profile['eligibility'] = check(profile)
        profile['index_eligibility'] = profile['eligibility']['detail']
        if profile['eligibility']['track_d'] is False:
            raise ValueError(profile['eligibility']['detail'])
        if hasattr(self.web,'issuer_links'):
            links = self.web.issuer_links(self.store,sources)
            if links and not profile.get('official_domain'):
                profile['official_domain'] = (urlparse(links[0]['url']).hostname or '').removeprefix('www.')
                profile['official_domain_evidence'] = links[0]
                state['warnings'].append('Issuer website located through an explicit directory hyperlink; this is a discovery lead, not independent corroboration.')
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
        reserve = min(6, max(2, self.limits.sources // 3))
        self.follow_disclosures(state, max_new=3, budget_reserve=reserve)
        angles = state['plan']['angles'][:3]
        if self.limits.fast_mode:
            # Seek an outside perspective before spending the whole retrieval
            # window on additional copies of the issuer's own disclosures.
            angles = sorted(angles,key=lambda a:not bool(re.search(r'FDA|regulat|competitor|industry|sector', ' '.join(a['queries']),re.I)))
        for angle in angles:
            for query in angle["queries"][:1 if self.limits.fast_mode else 2]:
                if self.limits.fast_mode and self.remaining(state) < 165:
                    break
                if state["usage"]["searches"] >= self.limits.searches or state["usage"]["sources"] >= self.limits.sources - reserve:
                    break
                scoped = state['profile']['name'] + ' ' + query
                self.collect(state, sorted(self.search(state, scoped), key=disclosure_score, reverse=True), limit=1, budget_reserve=reserve)
        if not self.limits.fast_mode:
            self.follow_disclosures(state, max_new=2, budget_reserve=reserve)
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
                cutoff = int(state['as_of'][:4]) - state['years']
                links = [r for r in links if not document_year(r) or cutoff <= document_year(r) <= int(state['as_of'][:4])]
                links.sort(key=lambda r:(document_year(r),disclosure_score(r)),reverse=True)
                # Keep a baseline report as well as recent disclosures when available.
                if room >= 3 and len(links)>3:
                    dated = [r for r in links[2:] if document_year(r)]
                    if dated:
                        baseline = min(dated,key=document_year)
                        links = links[:2] + [baseline] + [r for r in links[2:] if r is not baseline]
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
            if len(chosen) < self.limits.pages_per_source and p>1:
                chosen.setdefault(p-1,source['pages'][p-2])
        pages = []
        for p,text in sorted(chosen.items()):
            headers = []
            for line in text.splitlines():
                years = re.findall(r'(?<!\d)20\d{2}(?!\d)',line)
                if 2 <= len(years) <= 5 and len(years)==len(set(years)):
                    headers.append({'page':p,'quote':line.strip()})
            pages.append({'page':p,'text':text[:16000], 'section_context':section_scope(source,p),
                          'column_header_candidates':headers[:4]})
        return pages

    def extraction_request(self, state, source):
        return ("Extract up to 10 relevant source facts for financial discovery, prioritizing comparable financial rows, contradictions, reporting changes and dated events. "
                "Every fact quote must be verbatim on its cited physical page. statement must be fully supported by quote. "
                "For numeric facts, give the original number as decimal text without commas, metric, fiscal_period, currency, original unit, "
                "Use the SAME metric and definition labels for comparable measurements across periods. definition describes the "
                "When a comparative table provides two years, extract BOTH values for each selected metric as separate facts "
                "with the same metric/definition. Prioritize comparable revenue and profit pairs before isolated one-year figures. "
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
                "Each numeric table row needs the verbatim year header and grounded standalone/consolidated scope. "
                "column_header is REQUIRED on every returned fact. For a multi-value table row, set it to the EXACT separate "
                "column-header row containing all fiscal years in left-to-right order. Use column_header_candidates when they match "
                "the actual table. Do not quote the report title, a single year, or a whole paragraph as the column_header. "
                "For qualitative facts or a single inline value with its own year use {page:0,quote:''}. "
                "Keep context_evidence for separate unit/currency and reporting-basis passages. "
                "section_context identifies a verified preceding section heading and can be cited at its physical page. "
                "Only extract financial figures within the supplied research_window. Older events may be historical context, not current financial inputs. "
                "Extract numeric values, not just earnings schedules; return empty facts when the document has no substantive business evidence.",
                {"company": state["profile"], "source_id": source["id"], "url": source["url"],
                                "title": source["title"], "pages": self.selected_pages(source),
                                'research_window':{'as_of':state['as_of'],'earliest_financial_year':int(state['as_of'][:4])-state['years']}} )

    def prefetch_extractions(self, state, sources):
        """Parallel isolated model clients; reserve, validate and commit on this thread."""
        self.prefetch_failures = set()
        pool = ThreadPoolExecutor(max_workers=3)
        futures = {}
        try:
            eligible = []
            for source in sources:
                if source['id'] in state['extracted'] or source_issue(source, state['profile']):
                    continue
                if source.get('published') and source['published'] > state['as_of']:
                    continue
                year = document_year(source)
                if year and year < int(state['as_of'][:4]) - state['years']:
                    continue
                if hasattr(self.web, 'is_report_index') and self.web.is_report_index(self.store, source):
                    continue
                eligible.append(source)
            # Small waves keep context bounded, allow progress saves, and leave review time.
            width = 6 if self.limits.pages_per_source >= 8 else 4
            selected = eligible[:width]
            domain = state['profile'].get('official_domain','')
            independent_leads = [s for s in eligible if domain and not host_is((urlparse(s.get('url','')).hostname or '').removeprefix('www.'),domain)
                                 and not any(host_is((urlparse(s.get('url','')).hostname or ''),d) for d in NON_ISSUER_DOMAINS if d not in {'fda.gov','sec.gov'})]
            if independent_leads and independent_leads[0] not in selected:
                selected[-1] = independent_leads[0]
            self.prefetch_failures.update(s['id'] for s in eligible if s not in selected)
            if len(eligible) > width:
                state['warnings'].append('Additional archived documents remain unextracted in this bounded cycle.')
            for offset in range(0, len(selected), 3):
                if self.remaining(state) <= self.finish_reserve(state) + 28:
                    self.prefetch_failures.update(s['id'] for s in selected[offset:])
                    break
                for source in selected[offset:offset+3]:
                    stage = 'extract:' + source['id']
                    task, data = self.extraction_request(state, source)
                    key = self.cache_key(state, stage, task, schemas.FACTS, data)
                    if self.store.cache(key) is not None:
                        continue
                    if state['usage']['model_calls'] >= self.limits.model_calls - 5:
                        self.prefetch_failures.add(source['id'])
                        continue
                    self.reserve(state, 'model_calls')
                    client = copy(self.model)
                    generate = getattr(client, 'generate_bounded', client.generate)
                    self.event(state, 'model', 'Extracting archived document in parallel: ' + source['id'])
                    future = pool.submit(generate, task, schemas.FACTS, data, timeout=min(25, self.remaining(state) - self.finish_reserve(state)))
                    futures[future] = (source, key, client)
                while futures:
                    self.remaining(state)
                    done, _ = wait(futures, timeout=.2, return_when=FIRST_COMPLETED)
                    for future in done:
                        source, key, client = futures.pop(future)
                        try:
                            result = future.result()
                            validate(result, schemas.FACTS)
                            self.store.cache(key, result)
                            state['usage']['model_usage'].append(getattr(client, 'last_usage', {}))
                        except (ValueError, OSError) as exc:
                            self.prefetch_failures.add(source['id'])
                            state['warnings'].append(f"Extraction deferred for {source['id']}: {type(exc).__name__}. No facts accepted from this response.")
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    def extract(self, state):
        existing = {f["id"] for f in state["facts"]}
        ordered_sources = sorted(self.sources(state), key=lambda s: (str(s.get('original_archive', s.get('archived', ''))).lower().endswith('.pdf'),
                                  document_year(s),disclosure_score(s)),reverse=True)
        if self.limits.fast_mode:
            self.prefetch_extractions(state, ordered_sources)
        for source in ordered_sources:
            if self.limits.fast_mode and source['id'] in self.prefetch_failures:
                continue
            if source["id"] in state["extracted"]:
                continue
            year = document_year(source)
            if (year and year < int(state['as_of'][:4])-state['years'] and str(source.get('original_archive',source.get('archived',''))).endswith('.pdf')) or source_issue(source,state['profile']):
                reason = source_issue(source,state['profile']) or 'Document predates the requested financial research window.'
                self.event(state,'extract','Skipped evidence: '+reason)
                state['extracted'].append(source['id'])
                continue
            numeric_count = sum(f['kind'] == 'financial' and bool(f['value']) for f in state['facts'])
            reserved_calls = min(6, self.limits.model_calls // 3)
            if not self.limits.fast_mode and numeric_count >= 2 and (state['usage']['model_calls'] >= self.limits.model_calls - reserved_calls or
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
            task, data = self.extraction_request(state, source)
            result = self.model_call(state, "extract:" + source["id"], task, schemas.FACTS, data)
            facts, errors = extract_facts(source, result["facts"])
            facts, scope_errors = company_financial_facts(facts, state['profile'])
            errors += scope_errors
            # Save validated facts before attempting a potentially failing repair request.
            retained = [f for f in current_facts(facts,state['as_of'],state['years']) if not f['event_date'] or f['event_date'] <= state['as_of']]
            state['facts'].extend(f for f in retained if f['id'] not in existing)
            existing.update(f['id'] for f in retained)
            self.store.checkpoint(state)
            if errors and (not self.limits.fast_mode or (not facts and self.remaining(state) > self.finish_reserve(state) + 30)):
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
                    "Set column_header to the separate verbatim row containing ALL year columns in their actual order, "
                    "using supplied column_header_candidates. Never substitute a report title or a single year. "
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
                facts, scope_errors = company_financial_facts(facts, state['profile'])
                errors += scope_errors
                facts = list({f["id"]: f for f in original_facts + facts}.values())
            historical = [f for f in current_facts(facts,state['as_of'],state['years']) if not f["event_date"] or f["event_date"] <= state["as_of"]]
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
        if (len(numeric) < 2 or not self.calculation_candidates(state)) and not state["hypotheses"]:
            if self.recover_financial_evidence(state):
                return "extract"
            state["warnings"].append("Insufficient financial evidence to form a hypothesis: recent comparable, anchored financial numbers and a valid relationship are required. Scheduling notices do not establish a financial discovery.")
            return "compose"
        return "hypothesize" if not state["hypotheses"] else "skeptic"

    def hypothesize(self, state):
        # Suggest only mechanically comparable pairs; never manufacture missing inputs.
        candidates = self.calculation_candidates(state)
        context = {**self.context(state), "validated_calculation_candidates": candidates}
        result = self.model_call(state, "hypothesize", "Propose up to 3 non-obvious, financially meaningful hypotheses based only on facts. "
            "Cite existing fact IDs. Design tests that could disprove each. Propose up to 3 supporting AND opposing search queries each. "
            "Request calculations using exactly two numeric fact IDs: share/margin_pct = first/second*100 (same fiscal period); "
            "growth_pct=(second/first-1)*100 (same metric across periods); difference=second-first; cagr_pct uses a verified year interval. "
            "Use globally unique calculation IDs and do not reuse IDs. Prefer hypotheses with a measurable financial relationship. "
            "Every hypothesis MUST cite two numeric financial facts and request at least one valid calculation on its supporting facts. "
            "An earnings date or call schedule is not a business-model shift, financial effect, or trading-volatility measurement. "
            "Do not propose price/volume/institutional-trading relationships without actual price/volume/ownership evidence. "
            "validated_calculation_candidates contains mechanically checked comparisons, not discoveries. Use those exact inputs where relevant. "
            "A hypothesis is not a conclusion; do not present unsupported causes as established facts. Return no hypotheses if inadequate.", schemas.HYPOTHESES, context)
        before = len(state["hypotheses"])
        warning_start = len(state["warnings"])
        self.accept_hypotheses(state, result)
        if result["hypotheses"] and len(state["hypotheses"]) == before and self.can_repair(state):
            repaired = self.model_call(state, "repair-hypotheses", 
                "Repair rejected hypotheses using the supplied validation errors and actual fact IDs. "
                "Use a validated calculation candidate only if it supports the proposed financial relationship. "
                "Do not change reporting definitions or entity scope to force comparability. Return no hypotheses if unsupported.",
                schemas.HYPOTHESES, {**context, "previous_output": result,
                                     "validation_errors": state["warnings"][warning_start:]})
            self.accept_hypotheses(state, repaired)
        state["pending_queries"] = [q for h in state["hypotheses"] for q in h["followup_queries"][:3]]
        return "followup" if state["hypotheses"] else "compose"

    def can_repair(self, state):
        # Keep three calls for composition/audit and a further review attempt.
        return (state["usage"]["model_calls"] < self.limits.model_calls - 3
                and self.remaining(state) > (self.finish_reserve(state) + 25 if self.limits.fast_mode else 30))

    def calculation_candidates(self, state):
        facts = {f["id"]: f for f in current_facts(state['facts'],state.get('as_of',now()[:10]),state.get('years',5)) if f["kind"] == "financial" and f["value"]}
        groups = {}
        for f in facts.values():
            key = tuple(norm(f[field]) for field in ("entity", "metric", "currency", "basis", "definition"))
            groups.setdefault(key, []).append(f)
        candidates = []
        for rows in groups.values():
            rows = sorted(rows, key=lambda f: f["fiscal_period"])
            for a, b in zip(rows, rows[1:]):
                spec = {"id": "comparison-" + digest((a["id"] + b["id"]).encode())[:10],
                        "operation": "growth_pct", "inputs": [a["id"], b["id"]], "years": 0,
                        "purpose": "Reported change in " + a["metric"]}
                try:
                    candidates.append(calculation(spec, facts))
                except ValueError:
                    continue
                if len(candidates) >= 24:
                    return candidates
        return candidates

    def accept_hypotheses(self, state, result):
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

    def followup(self, state):
        state["round"] += 1
        for query in state["pending_queries"][:2 if self.limits.fast_mode else 4]:
            if self.limits.fast_mode and self.remaining(state) <= self.finish_reserve(state) + 35:
                state['warnings'].append('Further searches deferred to preserve contradiction review and claim auditing time.')
                break
            if state["usage"]["searches"] >= self.limits.searches or state["usage"]["sources"] >= self.limits.sources:
                state["warnings"].append("Supporting/opposing research stopped at the configured search/source budget.")
                break
            # Generic accounting queries otherwise fetch tutorials instead of company evidence.
            company = state.get('profile', {}).get('name') or state['company']
            scoped_query = company + ' ' + query
            self.collect(state, sorted(self.search(state, scoped_query), key=disclosure_score, reverse=True), limit=1)
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
        warning_start = len(state['warnings'])
        reviews = self.checked_reviews(state, result)
        missing = {h["id"] for h in state["hypotheses"]} - {r["hypothesis_id"] for r in reviews}
        if missing and self.can_repair(state):
            repaired = self.model_call(state, "repair-skeptic:" + str(state["round"]),
                "Repair the missing skeptic reviews. Cite ONLY exact fact IDs from the supplied facts and exact hypothesis IDs. "
                "Do not invent evidence or erase contradictions. Leave alternatives unresolved when evidence is missing. "
                "A future_test needs a finite threshold and dates strictly after as_of. "
                "threshold must be DECIMAL TEXT ONLY, e.g. '5000', never '5000 Million INR', a percentage symbol, commas, "
                "or a verbal range. Put units in metric, preserving the proposed number and comparison. "
                "Address the specific validation_errors; do not alter evidence to fix formatting. Return reviews for the missing IDs only.",
                schemas.SKEPTIC, {**self.context(state), "hypotheses": state["hypotheses"],
                                  "missing_hypothesis_ids": sorted(missing), "rejected_output": result,
                                  "validation_errors": state['warnings'][warning_start:]})
            reviews += [r for r in self.checked_reviews(state, repaired) if r["hypothesis_id"] in missing]
        state["reviews"] = reviews
        state["pending_queries"] = [q for r in reviews for q in r["followup_queries"][:2]]
        if state["round"] < self.limits.rounds and state["pending_queries"] and state["usage"]["sources"] < self.limits.sources and state["usage"]["searches"] < self.limits.searches:
            return "followup"
        return "compose"

    def checked_reviews(self, state, result):
        from .evidence import validate_future_test
        known = {f["id"] for f in state["facts"]}
        hypotheses = {h["id"] for h in state["hypotheses"]}
        reviews = []
        for review in result["reviews"]:
            cited = review["supporting_facts"] + review["opposing_facts"] + review["chronology_evidence"]
            cited += [fid for t in review["alternative_tests"] for fid in t["evidence"]]
            if review["hypothesis_id"] in hypotheses and all(fid in known for fid in cited) and not any(r["hypothesis_id"] == review["hypothesis_id"] for r in reviews):
                try:
                    validate_future_test(review.get("future_test"), state["as_of"])
                except (ValueError, KeyError, TypeError) as exc:
                    state["warnings"].append("Rejected skeptic review: " + str(exc))
                    continue
                for test in review["alternative_tests"]:
                    if not test["evidence"]:
                        test["outcome"] = "unresolved"
                reviews.append(review)
            else:
                state["warnings"].append("Rejected skeptic review with unknown hypothesis or evidence IDs.")
        return reviews

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
        reviewed = self.snapshot(state)
        state['findings'] = reviewed['findings']
        state['withheld_findings'] = reviewed.get('withheld_findings',[])
        state["status"] = "completed" if any(f["status"] == "supported" for f in state["findings"]) else "insufficient_evidence"
        return "done"

    def snapshot(self, state):
        from .eligibility import check
        profile = dict(state.get('profile',{}))
        if profile:
            profile['eligibility'] = check(profile)
            profile['index_eligibility'] = profile['eligibility']['detail']
        return publication_view({"id": state["id"], "kind": "research", "company": state["company"], "created": state["created"],
                "status": state["status"], "demo": False, "engine": "LangGraph hypothesis-evidence-contradiction investigation",
                "profile": profile, "plan": state.get("plan", {}), "parameters": state["limits"], "as_of": state["as_of"],
                "usage": state["usage"], "events": state["events"], "findings": state["findings"], "warnings": state["warnings"],
                "facts": state["facts"], "observations": self.store.observations(state["company"]), "sources": self.sources(state),
                "hypotheses": state["hypotheses"], "reviews": state["reviews"], "calculations": state["calculations"],
                'years':state.get('years',5),'withheld_findings':state.get('withheld_findings',[]),'evidence_policy':VERSION})

    def run(self, company=None, years=5, as_of=None, resume=None, run_id=None):
        from langgraph.graph import END, START, StateGraph
        if resume:
            state = self.store.agent_state(resume)
            if state.get('profile') and not identity_matches(state['company'],state['profile']):
                state['profile']={}
                state['facts'],state['hypotheses'],state['reviews'],state['findings']=[],[],[],[]
                state['calculations']={}
                state['source_ids'],state['attempted_urls'],state['extracted']=[],[],[]
                state['next_stage']='resolve'
                state['warnings'].append('Previous company identity did not match the requested entity. Retained the archive and restarted identity resolution.')
            if state.get('evidence_policy') != VERSION:
                state['facts'] = current_facts(state['facts'],state['as_of'],state.get('years',5))
                state['hypotheses'],state['reviews'],state['calculations'],state['findings'] = [],[],{},[]
                state['extracted'] = []
                state['financial_recovery_attempted'] = False
                state['next_stage'] = 'gather' if state.get('profile') else 'resolve'
                state['evidence_policy'] = VERSION
                domain = state.get('profile',{}).get('official_domain','')
                if any(host_is(domain,d) for d in NON_ISSUER_DOMAINS):
                    state['profile']['official_domain'] = ''
                if hasattr(self.web,'issuer_links') and not state.get('profile',{}).get('official_domain'):
                    links = self.web.issuer_links(self.store,self.sources(state))
                    if links:
                        state['profile']['official_domain'] = (urlparse(links[0]['url']).hostname or '').removeprefix('www.')
                state['warnings'].append('Evidence-policy upgrade: retained source archive; rebuilding recent comparable evidence and interpretations.')
            previous_ids = {f['id'] for f in state['facts']}
            state['facts'], scope_errors = company_financial_facts(state['facts'], state.get('profile', {}))
            state['warnings'].extend('Excluded archived fact: ' + error for error in scope_errors)
            excluded_ids = previous_ids - {f['id'] for f in state['facts']}
            used_ids = {fid for h in state['hypotheses'] for fid in h['supporting_facts'] + h['opposing_facts']}
            used_ids |= {fid for c in state['calculations'].values() for fid in c['inputs']}
            if excluded_ids & used_ids:
                state['hypotheses'], state['reviews'], state['findings'], state['calculations'] = [], [], [], {}
                state['status'], state['next_stage'] = 'insufficient_evidence', 'done'
                state['warnings'].append('Prior interpretations used out-of-scope financial inputs and require fresh review.')
            state["search_failure_streak"] = 0
            if state["next_stage"] == "extract" and not state["facts"]:
                state["extracted"] = []
            state["limits"] = asdict(self.limits)
            if state["next_stage"] == "done":
                if state["status"] == "completed":
                    return self.snapshot(state)
                # An explicit resume must do research, rather than re-export the same failure.
                if (state["usage"]["model_calls"] >= self.limits.model_calls or
                        state["elapsed"] >= self.limits.seconds):
                    raise BudgetExceeded("Continuing this investigation needs a larger total time and model-call budget.")
                state["round"] = 0
                state["reviews"] = []
                state["findings"] = []
                pending = set(state["source_ids"]) - set(state["extracted"])
                if pending:
                    state["next_stage"] = "extract"
                elif state["hypotheses"]:
                    state["pending_queries"] = [q for h in state["hypotheses"] for q in h["followup_queries"][:3]]
                    state["next_stage"] = "followup"
                else:
                    state["next_stage"] = "hypothesize" if len(state["facts"]) >= 2 else "gather"
                self.event(state, "resume", "Continuing an incomplete investigation using archived evidence and the new total budgets.")
        else:
            if not company or not company.strip() or years < 2:
                raise ValueError("A company and at least two research years are required.")
            if run_id and (not re.fullmatch(r'run-[a-f0-9]{10}', run_id) or self.store.db.execute('SELECT id FROM runs WHERE id=?', (run_id,)).fetchone()):
                raise ValueError('Investigation ID is invalid or already exists.')
            state = {"id": run_id or uid("run"), "company": company.strip().upper(), "created": now(), "as_of": as_of or now()[:10],
                "years": years, "limits": asdict(self.limits), "status": "running", "next_stage": "resolve", "elapsed": 0,
                "usage": {"searches": 0, "sources": 0, "model_calls": 0, "cache_hits": 0, "model_usage": []},
                "events": [], "warnings": [], "source_ids": [], "attempted_urls": [], "facts": [], "extracted": [],
                "hypotheses": [], "reviews": [], "calculations": {}, "findings": [], "round": 0, "pending_queries": []}
            state['evidence_policy'] = VERSION
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
                    current["status"] = "interrupted" if isinstance(exc, (KeyboardInterrupt, ResearchPaused)) else "budget_exhausted" if isinstance(exc, BudgetExceeded) else "failed"
                    if isinstance(exc, (BudgetExceeded, TransientModelError, IdentityResolutionError)):
                        current['warnings'].append(str(exc))
                        self.event(current, stage, str(exc))
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
