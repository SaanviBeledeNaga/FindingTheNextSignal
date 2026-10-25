# Pharma Scope: technical appendix

## Validation contract

Every model-produced fact has a dedicated `column_header: {page, quote}` field. For a multi-value financial table row it must cite the separate, verbatim header row containing the actual fiscal years in left-to-right order. A report title, a lone year and an invented stitched quotation do not assign table columns. Inline or qualitative facts can use an empty header object. The schema requires the field; the validator also checks the source quote, page, year ordering and corresponding value. Legacy records can use an equivalent valid header already present in `context_evidence`.

Financial statement pages receive detailed layout reconstruction before keyword-dense notes. The model receives source-derived candidate header rows. Old PDF text can be refreshed under the new parser version without changing original document bytes. Failed or ambiguous extraction remains excluded; this is a text-layout improvement, not OCR or a complete visual-table verifier.

Additional checks cover page bounds, exact passages, original values, reporting-basis context, company/subsidiary scope, period window, future dates, source relevance and document previews. Unit plurals can be normalised without changing scale. Schema and quote checks do not prove that a statement's meaning is correct.

## Calculations

The calculation engine uses Decimal and referenced fact IDs. Supported operations: share, margin, growth, difference and CAGR. It checks entity, currency, reporting basis and applicable definition/period compatibility; normalises monetary scales; rejects duplicate inputs and invalid denominators; and verifies annual intervals for CAGR. Current automatic candidate generation emphasises comparable growth pairs. Dedicated working-capital metrics and broader ratio discovery remain incomplete.

## Origin and claim checks

Issuer disclosures and copies of issuer filings share an issuer origin. Certain official regulator origins can independently corroborate a claim; regulator subdomains are grouped under their agency. Unverified news, industry and competitor labels do not automatically establish independence. Different URLs or file hashes alone do not prove independent support.

Finding validation requires cited claims, three to five significance bullets, supported timeline dates/periods, relevant calculations, a counterargument and a structured future falsification test. Causal claims require dated ordering and evidenced alternative tests. The separate claim audit can withhold a draft even when its citations exist. It uses the configured model and is not independent human verification.

Read-time publication checks also filter older facts and findings. Excluded inputs remove dependent calculations and interpretations from public views. The raw archive remains available; raw storage should not be confused with the current admitted evidence set.

## Statuses and evidence ratings

| Label | Meaning |
|---|---|
| Supported | Passed implemented support gates; not a truth guarantee. |
| Unresolved | A retained interpretation with material uncertainty. |
| Rejected | Review rejected the explanation. |
| Withheld | A draft or archived claim failed publication checks. |
| Insufficient Evidence | No supported discovery established in the cycle. |
| Budget Exhausted | A configured limit stopped the investigation. |
| Failed / Interrupted | A provider, process or user interruption stopped work. |

Strong/Moderate/Weak are deterministic categories based on implemented origin, contradiction, alternative and chronology checks. They are not calibrated probabilities of truth or a universal five-criterion certification.

## Budgets and timing

| Limit | Standard | Wider |
|---|---:|---:|
| Research budget | 270s | 270s |
| Source requests, including failures | 12 | 16 |
| Searches | 8 | 10 |
| Model attempts | 20 | 24 |
| Selected pages per source | 6 | 8 |
| Retained hypotheses | 2 | 2 |
| Follow-up-round limit | 1 | 1 |

Concurrent document downloads/extraction are limited to three. Fast-mode model calls have deadlines up to 25s, PDF parsing up to 12s, and the dashboard supervisor stops a stalled worker at 280s. Checkpointing, export and display can add overhead. Bounded 270s cycle is the product wording; it is not a promise of a complete investigation or an insight within that time. CLI budgets can be explicitly configured differently and are cumulative on resume.

## Eligibility

`pharma_scope/data/nifty50.json` stores 50 official constituent rows, industry labels, source URL, download timestamp and content hash. Exact normalised names/symbols are matched conservatively. Healthcare-classified members qualify for Track D in that snapshot. Other NIFTY sectors are outside the track. Nonmembers remain extended-universe research with sector eligibility unverified. No invented effective date or historical membership is attached to the snapshot.

## Storage, privacy and deployment

SQLite stores run state, source metadata, facts and cached model/tool responses. `.pharma/archive` stores original documents; `.pharma/jobs` stores worker records; `.pharma/exports` stores evidence reports. API settings remain in `.env` and backend environment variables. Public excerpts are transmitted to the configured model; optional external tracing can transmit workflow context. The dashboard binds to loopback and is not remote hosting. Release archives exclude secrets and research data.

## Remaining limitations

Scanned-report OCR is not bundled. First-mainstream-coverage comparison is not implemented. Full five-year geographic drivers, broad independent corroboration, automatic restatement reconciliation, novelty assessment and reliable performance across all unseen companies remain unproven. See the live evaluation rather than inferring research quality from software test counts.
