# PHARMA-SCOPE

An autonomous public-source research agent plus a terminal workbench. Version 0.2 adds a LangGraph investigation workflow, Gemini/OpenAI model adapters, Brave/Tavily search, supporting and opposing research, bounded retries through saved checkpoints, and a professional evidence report. The original offline geographic analysis remains available.

Version 0.3.0 improves primary-document retrieval, separately cited financial table context, hypothesis admission and claim review. See [DEPLOYMENT.md](DEPLOYMENT.md) for installation, Codespaces, persistent data, updates and rollback.

## Research quality changes in 0.3

- Follow two bounded levels of official financial indexes, including directly linked CDN PDFs. Prioritize annual statements and results over call invitations. Source links are retrieval leads, not automatic independent corroboration.
- Numeric rows can cite separate verbatim column headers, units and reporting basis. These passages are checked against their own physical pages and displayed in the report. Original unit case is normalized. Actual income-statement pages receive reserved selection slots.
- Repair partially invalid extraction while retaining valid facts. Attempt one bounded financial-evidence recovery when fewer than two numeric financial facts are available.
- Require two numeric financial facts and a valid calculation on the hypothesis's supporting evidence. Scheduling-only documents cannot produce a hypothesis. A discovery must cite a calculation.
- Run a separate model review of claim support, column interpretation and sector relevance before publication. This is an additional fallible model check, not a proof of semantic correctness.
- Require a structured falsification metric, numerical threshold, expected public source and observation window after the investigation date. Thresholds are explicitly proposed tests, not source-derived facts.

Start a **new** investigation after updating to exercise the full pipeline; resuming a completed old run does not reevaluate its findings. Existing archived reports remain readable. An actual Sun Pharma FY2025 financial PDF extraction check retained numeric facts and supported comparable Python calculations. This is evidence of extraction progress, not a proven non-obvious discovery or finals readiness.

A subsequent live autonomous Sun Pharma run collected 13 sources and retained 40 facts. A separate claim review withheld its draft discovery because the R&D-versus-revenue growth interpretation contradicted the cited figures. The run ended with `insufficient_evidence`, not a supported discovery. Intermittent Gemini 503 responses required retries. Budget reservations for opposing sources and final reasoning were strengthened after this evaluation. No claim of successful independent corroboration or non-obvious discovery is made from that run. Legacy Windows console output was also corrected so a rupee symbol cannot turn successful report export into a terminal encoding error.

## Live research setup

### Search without a card or search API key

If Brave/Tavily onboarding requires billing, use the optional DDGS DuckDuckGo adapter:

```powershell
python -m pip install -e ".[search]"
```

Set `PHARMA_SEARCH_PROVIDER=duckduckgo` in `.env`. No `BRAVE_API_KEY` or `TAVILY_API_KEY` is needed for this provider; Gemini settings are still required. This is a third-party search library, not an official DuckDuckGo API. It tries DuckDuckGo, then a public Bing backend if necessary, sharing the logical query timeout between them. It reports empty/failed searches and does not bypass captchas or access controls. Availability/rate limits can vary. `doctor` shows whether the optional package is installed. Search failures are recorded as incomplete coverage; the research loop continues with readable sources rather than discarding them. After two consecutive account-free search failures, additional queries in that run are skipped. Official report-index links are also followed where available. Public Bing search has been live-tested from this environment.

During live diagnostics, `gemini-3.8-flash` returned HTTP 503 while `gemini-3.5-flash-lite` returned valid structured JSON and completed company identification and planning. To try that alternative without editing your key, pass `--model gemini-3.5-flash-lite`; availability is account- and time-dependent. The app does not silently switch models.

An initial live Cipla investigation with Gemini Flash-Lite and account-free search completed with `insufficient_evidence`: five sources were collected, but no extracted facts passed validation. Newer local Cipla and Dr. Reddy's investigations each collected nine sources, retained six facts and produced one unresolved, Weak hypothesis; neither established a supported discovery. These runs verify execution and conservative withholding, not discovery quality. Real-document extraction and independent corroboration remain material limitations requiring improvement and evaluation before claiming finals readiness.

DDGS documentation: https://pypi.org/project/ddgs/

The selected configuration is **Gemini API + Brave Search**. LangGraph runs the workflow; LangSmith is optional tracing/evaluation infrastructure, not the model provider. Gemini CLI is not required.

```powershell
python -m pip install -e ".[ai,dev]"
# Create .env from .env.example if you do not already have one.
if (-not (Test-Path -LiteralPath .env)) { Copy-Item -LiteralPath .env.example -Destination .env }
```

Edit `.env` locally and set `GEMINI_API_KEY`, `BRAVE_API_KEY`, and `PHARMA_MODEL` to a Gemini model available to your account that supports structured JSON output. The application does not assume a particular model ID or subscription. Keys are never printed by the setup check. `.env` is excluded from source packages and version control.

```powershell
python -m pharma_scope doctor
python -m pharma_scope investigate "Sun Pharmaceutical Industries" --seconds 600 --output sun-pharma-report.html
python -m pharma_scope investigate "Cipla" --tui
```

`doctor` checks whether settings are present; it does not validate subscriptions or spend API credits. A live run is needed to validate credentials and model access.

The live workflow resolves company identity, plans research, searches public sources, archives HTML/PDF documents, extracts anchored facts, proposes testable hypotheses, runs supporting/opposing searches, calculates requested metrics in Python, challenges explanations, and publishes findings. Search snippets are discovery leads; only fetched passages can support findings. Unknown publication dates stay unknown. It investigates geography, business model and regulatory angles without hardcoded company findings.

The output is a self-contained HTML research report with all eight required elements, clickable claim-to-evidence anchors, original source links, calculation inputs, dates, source hashes, opposing evidence, rating justifications, and limitations. Markdown and JSON exports are also available. A result of `insufficient_evidence` is valid: unresolved/rejected hypotheses are labeled and do not become supported discoveries merely to fill a report.

### Budgets and resuming

Defaults: 600 active seconds, 16 searches, 18 source requests, 30 model calls, two investigation rounds, three hypotheses, ten relevant pages per source. Per-call timeouts are bounded by the remaining time budget. Source failures are recorded; model failures stop the run with a checkpoint. Counts include failed external attempts and persist across resumes. Source/page coverage is bounded and is not an exhaustive guarantee.

```powershell
python -m pharma_scope investigate "Company name" --max-searches 20 --max-sources 20 --max-model-calls 35 --rounds 2
python -m pharma_scope investigate --resume run-REPLACE --seconds 900 --max-model-calls 40
```

LangGraph controls transitions. SQLite stores explicit application checkpoints at stage/tool boundaries; this version does not use a native LangGraph SQLite checkpointer. Successful model/search results are cached per investigation to avoid repeating completed calls on resume. A process killed between an external response and its cache write can still repeat that call. Active-time budget resumes cumulatively. Token usage reported by providers is retained; the application does not estimate billing currency or impose a dollar cap.

Gemini HTTP 503/500/502/504, quota/rate-limit responses (429), and transport errors receive at most two automatic retries with increasing delays. A numeric `Retry-After` header is respected up to 30 seconds; longer waits stop with the checkpoint retained. Each attempt counts against the model-call budget. Authentication, permission and invalid-model errors are not automatically retried. The CLI prints stage starts, searches, downloads, model attempts and retry waits, so an initial model request no longer appears as a completely idle terminal. A 503 indicates temporary service unavailability, not evidence that a new API key or paid plan is required.

### Optional LangSmith tracing

Set `LANGSMITH_TRACING=true`, `LANGSMITH_API_KEY`, and optionally `LANGSMITH_PROJECT`. This sends graph traces, including evidence context, to your LangSmith account. Leave tracing false for local-only audit storage. LangSmith is not needed for agent execution. Tracing is instrumented but has not been live-verified without an account key.

### Plain-language terminal

The terminal opens with a summary: findings, supported/unresolved counts, budget usage and the top limitation. Each finding has a plain-language headline, a small revenue-share chart when applicable, significance bullets, alternative explanations with tested/untested labels, a falsification condition and numbered next actions. A pipeline separates completed research stages from unfinished verification. Related geographic shifts link to one another.

Press `?` for help and the glossary; focus the evidence badge and press Enter to see credibility, independence, consistency, comparability and contradiction criteria. Source names and dates are available without entering the full-passage view. Example question buttons fill the challenge input. Challenge replies appear inline; `R` repeats the local archive search after sources are added. These interactive questions are retrieval aids, not new live model verdicts. The autonomous agent's main research loop performs the live hypothesis tests. Detailed activity is on `L`; `B` reopens the summary; the footer changes with focus.

## Run on Windows

Requires Python 3.11 or newer. In PowerShell, open this folder and run:

```powershell
python -m pip install -e ".[ai,dev]"
python -m pharma_scope demo --tui
```

The machine used to build this project already had the runtime dependencies. There, the second command works immediately without installation. `start.ps1` runs that command from the project directory.

Installed command alias: `pharma demo --tui`. Without installation use `python -m pharma_scope` from this folder.

Keys: arrows select findings; Enter opens the finding; E shows passages; S shows alternative explanations; T adds the timeline; C focuses the question box; Enter submits a question; X exports HTML; ? opens help; L opens detailed activity; B opens the summary; R repeats the last question; Q exits. Typed shortcuts inside the input remain normal text. The UI works in a normal local terminal and can also run in a terminal on a remote machine over SSH. No server is required.

All demo data is fictional and labeled. DEMO has comparable five-year geographic disclosures. DEMO-BROKEN changes reporting definitions, so the engine withholds a drift conclusion.

```powershell
python -m pharma_scope demo
python -m pharma_scope discover --company DEMO-BROKEN
python -m pharma_scope discover --company DEMO --json
python -m pharma_scope export latest --format html
```

## Use real disclosures

1. Download annual reports yourself from their public source. Archive each report:

```powershell
python -m pharma_scope ingest "C:\reports\annual-report.pdf" --company SYMBOL --title "Annual report FY2025" --publisher "Issuer name" --published 2025-06-01 --url "https://issuer.example/report.pdf"
python -m pharma_scope sources --company SYMBOL
```

The example URL is a placeholder. Supply the actual source URL and publication date. PDFs preserve physical page numbers. Text and Markdown files use form-feed characters for page breaks. Scanned PDFs need OCR first. Ingestion is local and does not contact the URL. SHA-256 identifies the archived file; identical company/file imports are idempotent. Hashes detect identity, not publisher authenticity.

2. Create a CSV with the following columns. Replace the source ID and quote with actual returned IDs and exact table passages:

```csv
source_id,period,region,value,currency,unit,basis,definition,page,quote
src-REPLACE,2025,India,3000,INR,crore,consolidated,customer destination,120,"India revenue 3,000 INR crore"
src-REPLACE,2025,US,5000,INR,crore,consolidated,customer destination,120,"US revenue 5,000 INR crore"
src-REPLACE,2025,Other,2000,INR,crore,consolidated,customer destination,120,"Other revenue 2,000 INR crore"
src-REPLACE,2025,Total,10000,INR,crore,consolidated,customer destination,120,"Total revenue 10,000 INR crore"
```

`period` is the fiscal end year. `Total` is case-sensitive. Regions must be mutually exclusive and exhaustive. Every region and its total must use the same definition and reporting basis; a definition change must have a different label. Quotes must occur on the cited page and include the original number. Accepted units: units, thousand, lakh, million, crore, billion. Currency translation is not performed. Check values and units against table headers and footnotes yourself: quote validation cannot establish their semantic correctness.

```powershell
python -m pharma_scope import metrics.csv
python -m pharma_scope discover --company SYMBOL --years 5 --threshold 5
python -m pharma_scope tui latest
```

The engine checks reconciliation within a 1% tolerance, reporting definitions, currencies, consolidation basis, category stability, conflicting disclosures and missing periods. It normalizes monetary units with decimal arithmetic. Missing periods are flagged without interpolation. Restated and original amounts that disagree block comparison until resolved; source corrections are never silently applied.

## Optional model extraction

Set secrets in your current terminal environment; do not commit them. Choose a model available to your account that supports Responses API structured outputs. The app does not prescribe a model or make a call until `extract` is requested.

```powershell
$env:OPENAI_API_KEY = "your-key"
$env:PHARMA_MODEL = "your-model-id"
python -m pharma_scope extract src-REPLACE --pages 120-122 > extraction.json
```

This sends only the selected page text to OpenAI. Source text is treated as untrusted input. The result is schema constrained and checked against source quotes and numeric tokens. Default extraction previews JSON and does not import observations. After reviewing, either convert corrected observations to CSV and import, or rerun extraction with `--commit` to import the newly generated, validated result. A rerun can differ from the preview. No extraction is human-verified automatically. Incomplete responses, refusals and invalid evidence are rejected. Cost control: at most 100,000 input characters per extraction; 10,000 output tokens; timeout 90 seconds; at most one SDK retry.

API contract reference: https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses

## Challenge and audit

```powershell
python -m pharma_scope show latest --json
python -m pharma_scope challenge finding-REPLACE "Could currency translation explain this?" --run latest
python -m pharma_scope evidence obs-REPLACE
python -m pharma_scope export latest --format json --output dossier.json
python -m pharma_scope export latest --format md --output dossier.md
```

Challenges search all current local sources for the company, including newly ingested sources. Retrieved passages are candidates for review, not proof. Challenges remain unresolved and do not automatically upgrade or downgrade ratings. Reports retain the original run's observation/source snapshot, its calculations, events, and subsequent challenges. HTML exports escape source content and include source links; no remote assets or scripts are required.

The current rating is Moderate for a comparable, directly observed mix shift and Weak for withheld comparisons. Causal explanations remain unverified. Multiple reports from the same issuer do not count as independent corroboration. No Strong causal finding is issued by this version.

## What is implemented

- Local PDF/text ingestion and content-addressed archives.
- Validated CSV import; optional OpenAI-assisted extraction.
- Geographic mix discovery and deterministic skeptic checks.
- SQLite storage of sources, observations, run snapshots and challenges.
- Interactive Textual terminal UI, scriptable CLI and JSON output.
- HTML/Markdown/JSON dossiers, with the original arithmetic and provenance.
- LangGraph research workflow with persistent application checkpoints and explicit budgets.
- Gemini/OpenAI structured model providers and Brave/Tavily search adapters.
- Public HTML/PDF downloads with redirect checks and private-network destination blocking.
- Anchored fact extraction, financial calculations, supporting/opposing research and skeptic reviews.
- Conservative evidence gates and a professional research report with eight required elements.

## Known limits and verification status

The live workflow is implemented and tested end to end with fake external providers. A real public Sun Pharma financial PDF was downloaded, parsed and hashed successfully. Gemini/account-free search investigations have completed with insufficient evidence as described above; the Brave adapter has not been live-verified. No successful supported real-company autonomous discovery is claimed.

Source passages and original numeric tokens are mechanically anchored, but a valid quote can still be misinterpreted by a model. Numeric fields, company/subsidiary/facility relationships, source categories and geographic definitions need evaluation on real disclosures. Do not treat source hashes as publisher authentication. Regulatory chronology alone is not causal proof. Scanned PDFs require OCR; JavaScript-only sites, blocked pages and paywalls can remain inaccessible. Not all selected pages will contain the relevant table; bounded page sampling can miss evidence. Missing publication dates prevent strict historical point-in-time claims.

Independence is conservatively verified only for issuer-origin versus official regulator-origin evidence. Media/industry/competitor origin labels remain unverified rather than automatically inflating ratings. Repeated issuer filings share one origin. Unresolved alternatives cap causal conclusions; no evidence does not prove an alternative false. Source entity resolution is model-assisted and should not be presented as a verified corporate ownership database. Current/historical NIFTY membership is not established automatically; the same investigator accepts companies beyond the index.

The three angles are investigated through source-grounded hypotheses rather than three separately tuned engines. Scheduled monitoring, reviewed correction/recast workflows and large-scale company evaluation remain future extensions. The finals requirement of a successful unattended run on an unseen real company still requires credentialed live testing.

## Tests

```powershell
python -m pytest -q
```

The suite checks arithmetic, reporting changes, source anchoring, malicious report text, contradictory disclosures, isolation of demo data, CLI output and terminal interactions. Tests use temporary directories and never require network access or an API key.

## Project layout

`pharma_scope/cli.py` commands; `tui.py` workbench; `engine.py` investigation and skeptic; `ingest.py` extraction/validation; `ai.py` optional model adapter; `store.py` SQLite; `report.py` dossiers; `demo.py` fixtures. Research data defaults to `.pharma/` under the current working directory; use `--data-dir` before the command to override.
