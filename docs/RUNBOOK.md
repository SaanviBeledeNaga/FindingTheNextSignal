# Pharma Scope: runbook

## Install

Use Python 3.11 or newer. Open a terminal in the project folder; commands below are relative to that folder.

```powershell
python -m pip install -e ".[ai,search]"
```

## Configure

Preserve an existing `.env`. Create it from the template only when missing:

```powershell
if (-not (Test-Path -LiteralPath .env)) {
    Copy-Item -LiteralPath .env.example -Destination .env
}
notepad .env
```

Use a model ID available to the configured account. The following uppercase values are placeholders, not credentials:

```dotenv
PHARMA_PROVIDER=gemini
PHARMA_MODEL=YOUR_AVAILABLE_MODEL_ID
GEMINI_API_KEY=YOUR_LOCAL_KEY
PHARMA_SEARCH_PROVIDER=duckduckgo
LANGSMITH_TRACING=false
```

Keys stay in the local backend; `.env` must not be committed or shared. Public passages are sent to the configured model provider. Model quotas/costs are separate from account-free search. Brave, Tavily and OpenAI are optional adapters. External tracing, if enabled deliberately, can transmit workflow context to the tracing service.

```powershell
python -m pharma_scope doctor
```

Doctor checks settings and package presence, not live credential validity or model access. Restart the server after changing settings.

## Start the dashboard

```powershell
python -m pharma_scope web --open
```

Open [the local dashboard](http://127.0.0.1:8765/) if the browser does not open. Keep the terminal running. To use another port:

```powershell
python -m pharma_scope web --port 8888 --open
```

The server listens on loopback. A GitHub repository stores code; it does not run the server or publish this local address.

## Research and inspect

1. Choose **New Investigation** and enter a company name.
2. Choose Standard or Wider coverage. Both use a bounded 270s cycle.
3. Start research and follow Research Activity.
4. Read the final status. A finished cycle may contain no qualifying discovery.
5. Inspect source passages, column headers, fiscal periods, reporting scope, calculations and counterarguments.
6. Use Export for a portable evidence record.

The eligibility result identifies membership and Healthcare classification in a dated official snapshot. Nonmembers remain extended-universe cases; an unrelated NIFTY sector is rejected. This does not establish historical or continuously current membership.

## Pause and continue

Use **Pause Research** to request a cooperative pause. The current bounded request may finish before the checkpoint is saved. Use **Continue Research** for another bounded cycle with archived evidence and additional budgets. Completed supported runs require a fresh investigation to reassess them.

To stop the local server, press `Ctrl+C` in its terminal. Restart with the same `web --open` command; saved research remains in `.pharma`.

## Command-line research and export

```powershell
python -m pharma_scope investigate "Cipla" --seconds 270 --max-sources 16 --max-searches 10 --max-model-calls 24 --rounds 1
python -m pharma_scope export latest --format html
python -m pharma_scope export latest --format json
```

Open the exact saved HTML path printed by export:

```powershell
Start-Process "PATH_PRINTED_BY_EXPORT"
```

CLI resume limits are total cumulative limits, not additional allowances. Prefer the dashboard's Continue action unless deliberately calculating larger total budgets. Raw `show --json` is an archive inspection command; use `export --format json` for the publication-filtered research record.

## Check and refresh eligibility

```powershell
python -m pharma_scope eligibility "Cipla"
python -m pharma_scope eligibility --refresh
```

Refresh downloads the official constituent CSV and validates 50 unique symbols before replacing the snapshot. A failed refresh retains the existing file. A retrieved timestamp is not an index effective date.

## Reproduce the live evaluation

```powershell
python -m pharma_scope.evaluate --workers 2
```

The default six-company batch uses the same Wider settings for every company. At most two company workers run concurrently, and each has its own bounded cycle. Total batch time can span several cycles. It consumes model/search quota and saves all outcomes under `.pharma/evaluations/` plus normal run exports. To reduce concurrent provider load, use `--workers 1`.

The batch accepts 5–8 distinct company names:

```powershell
python -m pharma_scope.evaluate --workers 1 --companies "Cipla" "Dr. Reddy's Laboratories" "Sun Pharmaceutical Industries" "Lupin" "Zydus Lifesciences"
```

## Diagnose common failures

| Symptom | Action |
|---|---|
| No dashboard connection | Keep the server running; check the printed port. |
| Model authentication/access failure | Check local settings, account access and quota; do not share the key. |
| Search rate-limited | Read saved evidence; retry later or use an already-configured alternative adapter. |
| Investor page unreadable | The collector attempts full disclosures/catalogs; inspect retrieval warnings. |
| Table facts excluded | Inspect the row and separate year header. Do not bypass the column check. |
| No discovery | Review the actual evidence gap; more time cannot guarantee a result. |
| HTML file not found | Export the selected run first and open the exact printed path. |

## Development checks

```powershell
python -m pip install -e ".[ai,search,dev]"
python -m pytest -q
```

Some tests use fake providers for reproducibility. They do not establish live financial truth.
