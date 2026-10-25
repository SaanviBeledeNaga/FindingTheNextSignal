# Pharma Scope: overview

## Problem and intended result

Pharma Scope investigates public information about pharmaceutical and healthcare companies. Its goal is a non-obvious financial finding supported by an inspectable evidence trail. The research directions are business-model changes, regulatory effects on financial performance, and geographic revenue shifts.

The input is a company name. A qualifying finding contains a discovery sentence, three to five significance bullets, linked evidence, a timeline, necessary calculations, a counterargument, a measurable future falsification condition, and a reasoned evidence rating. An unresolved hypothesis is labelled as such; unsupported drafts are withheld.

## Research pipeline

1. **Identify and check eligibility.** Establish company identity from fetched passages. Match it against a dated official NIFTY 50 constituent snapshot and its industry classification. Companies outside the snapshot can be researched as extended-universe cases, without asserting sector or index eligibility.
2. **Plan.** Select research angles and public search queries without a company-specific preset conclusion.
3. **Collect.** Search public pages, follow disclosure links, download readable PDFs/HTML, and archive originals with URLs, timestamps and file hashes. Search snippets are leads, not evidence.
4. **Extract and validate.** Select financial pages and ask the model for structured facts. Each multi-value table fact needs a separate year-column header quote. Validate the row, header order, value, physical page, period, entity and reporting basis. Ambiguous facts are rejected.
5. **Calculate and hypothesise.** Python computes comparable growth, shares, margins, differences or CAGR. The model proposes explanations tied to actual fact and calculation IDs.
6. **Challenge.** Seek supporting and opposing evidence. Test alternatives such as currency effects, acquisitions, reporting changes and sector conditions. Missing evidence leaves a test unresolved.
7. **Audit and display.** Draft the eight output elements, audit semantic claim support, and apply publication gates. The dashboard and portable report show supported or unresolved findings, or explain why no finding qualified.

## Components and operating limits

The browser dashboard talks to a local Python server. LangGraph coordinates the workflow; the configured Gemini API interprets supplied material; DDGS provides account-free search. PyMuPDF and Beautiful Soup read documents, Decimal performs arithmetic, and SQLite stores checkpoints. Model requests and public downloads use the internet. LangSmith tracing is optional.

Both dashboard presets use a **bounded 270s cycle**. Standard allows up to 8 searches, 12 source requests, 20 model calls and 6 selected pages per source. Wider allows 10 searches, 16 source requests, 24 model calls and 8 pages. Wider changes coverage, not the time budget. Downloads and extraction use batches of at most three. A supervisor stops a stalled dashboard worker at 280s; saving and display can add overhead. These limits do not guarantee a discovery or successful retrieval.

## Real evaluation and demo

The reproducible batch evaluation uses identical Wider settings for eight companies: Cipla, Dr. Reddy's Laboratories, Sun Pharmaceutical Industries, Lupin, Zydus Lifesciences, Apollo Hospitals Enterprise, Max Healthcare Institute, and Divi's Laboratories. A general identity guard and comparable-pair guidance were added after the first six trials; earlier evidence was revalidated. All outcomes, including failed retrievals and withheld drafts, are retained. Selection prefers a supported finding, then an admissible unresolved finding; it does not relabel an unsuccessful result.

See [evaluation results](EVALUATION.md) for the actual outcomes and [real company walkthrough](REAL_CASE.md) for the strongest qualifying case, its calculations, source passages, counterargument and limitations. If no case qualifies, those documents state that explicitly. No fictional example substitutes for a live result. In this batch no finding qualified; the walkthrough documents Sun Pharma's real research attempt with no published discovery.

## What works and what remains unproven

Implemented: public collection, archived provenance, required column-header context, numeric and scope checks, calculations, hypothesis/skeptic stages, claim auditing, saved research, local dashboard, exports and a dated eligibility check.

Still incomplete: reliable novel discovery across unseen companies; independent competitor/industry/news corroboration; complete comparable five-year geographic coverage; scanned-report OCR; and systematic comparison with the first mainstream-coverage timestamp. The snapshot is not a live or historical index-membership service. A model review is not independent human verification, and an evidence badge is not a probability of truth.

The application does not provide investment recommendations. Software tests establish software behaviour; a separate live evidence review is needed to assess discovery quality.

## Further reading

- [Runbook](RUNBOOK.md): install, configure, start, research, resume and export.
- [Technical appendix](APPENDIX.md): validation rules, statuses, budgets and storage.
- [Requirements audit](../REQUIREMENTS.md): remaining gaps against the competition brief.
