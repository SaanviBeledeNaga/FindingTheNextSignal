# Live company evaluation

**Outcome: eight companies attempted; zero supported findings and zero publication-qualified unresolved findings.**

Every company used Wider budgets: a bounded 270s cycle, up to 10 searches, 16 source requests, 24 model attempts and 8 selected pages per source. Two company workers ran concurrently. Limits are maxima, not retrieval guarantees.

After the first six trials, a general identity-token guard and comparable-pair extraction guidance were added. All cases retain the same Wider budgets; public evidence is revalidated under the current policy.

| Company | Worker seconds | Accepted financial inputs | Supported | Unresolved | Status |
|---|---:|---:|---:|---:|---|
| Dr. Reddy's Laboratories | 121.72 | 0 | 0 | 0 | insufficient_evidence |
| Cipla | 162.77 | 4 | 0 | 0 | insufficient_evidence |
| Lupin | 17.33 | 0 | 0 | 0 | failed |
| Sun Pharmaceutical Industries | 197.09 | 27 | 0 | 0 | insufficient_evidence |
| Zydus Lifesciences | 163.78 | 0 | 0 | 0 | insufficient_evidence |
| Apollo Hospitals Enterprise | 80.06 | 0 | 0 | 0 | failed |
| Max Healthcare Institute | 40.11 | 0 | 0 | 0 | failed |
| Divi's Laboratories | 98.31 | 4 | 0 | 0 | insufficient_evidence |

## What the results show

The revised extraction retained four financial inputs for Cipla and 27 for Sun Pharma. Divi's retained four inputs but its proposed finding was withheld because it depended on a single source document. No outcome was relabelled to supply a success case.

The Apollo Hospitals trial resolved to Apollo Endosurgery. Its figures and interpretations are excluded by the new all-distinctive-token identity guard. That trial counts as a failure, not a healthcare-company success.

Search rate limits, blocked/unreadable pages, download deadlines and insufficient reporting context affected coverage. They are recorded below. The eight cases do not prove generality or novelty.

## Per-company evidence gaps

### Dr. Reddy's Laboratories
Run `run-3f104ef5de`; insufficient_evidence.
- Search unavailable for Dr. Reddy's Laboratories Limited Dr. Reddy's biosimilars revenue growth emerging markets annual report: Account-free search unavailable (DDGSException); it may be rate-limited. Retry later or use another provider.. Coverage is incomplete.
- Could not collect https://www.annualreports.com/HostedData/AnnualReportArchive/d/NYSE_RDY_2024.pdf: ValueError: Source download exceeded its total time budget.
- Could not collect https://www.annualreports.com/HostedData/AnnualReportArchive/d/NYSE_RDY_2021.pdf: ValueError: Source download exceeded its total time budget.
- Insufficient financial evidence to form a hypothesis: recent comparable, anchored financial numbers and a valid relationship are required. Scheduling notices do not establish a financial discovery.
- Insufficient evidence to publish a reviewed discovery.

### Cipla
Run `run-56398542a2`; insufficient_evidence.
- src-0d8bda5f96: rejected fact: numeric value not in quote
- src-0d8bda5f96: rejected fact: numeric value not in quote
- src-71bba29d83: rejected fact: table context quote not found on cited page
- src-71bba29d83: rejected fact: table context quote not found on cited page
- Withheld finding hypothesis-1: Claim contains an ungrounded number.

### Lupin
Run `run-acbaa47d3f`; failed.
Research stopped (ValueError). Saved evidence is retained; review the activity and continue research.
- Source-origin classification and semantic support are model-assessed; mechanically valid citations do not prove causation.
- Publication dates may be unknown. This is current public-source research, not a point-in-time backtest.
- Search unavailable for LUPIN pharmaceutical company official investor relations annual report: Account-free search unavailable (DDGSException); it may be rate-limited. Retry later or use another provider.. Coverage is incomplete.
- Search unavailable for LUPIN annual report consolidated financial statements filetype:pdf: Account-free search unavailable (DDGSException); it may be rate-limited. Retry later or use another provider.. Coverage is incomplete.

### Sun Pharmaceutical Industries
Run `run-588a851a3d`; insufficient_evidence.
Withheld: Unresolved hypothesis: Revenue from operations for Sun Pharmaceutical Industries Limited increased from 525,784.4 Million INR in FY2025 to 584,620.4 Million INR in FY2026, representing a growth rate of 11.19 percent.
- The discovery is not corroborated by at least two source documents.
- src-9997c21f72: future-dated events excluded from historical evidence.
- Could not collect https://www.sustainabilityreports.com/sun-pharmaceutical-industries/2026/annual-report: ValueError: Source retrieval failed (HTTP 403).
- src-bf1931f1d5: rejected fact: fiscal period year not in evidence quote
- src-bf1931f1d5: rejected fact: Reporting basis is not anchored in quoted context or the nearest financial section.
- Rejected skeptic review: Falsification threshold must be a finite number.

### Zydus Lifesciences
Run `run-a603e258da`; insufficient_evidence.
- src-209ec91c88: rejected fact: quote not found on cited page
- src-209ec91c88: rejected fact: quote not found on cited page
- src-209ec91c88: rejected fact: quote not found on cited page
- Insufficient financial evidence to form a hypothesis: recent comparable, anchored financial numbers and a valid relationship are required. Scheduling notices do not establish a financial discovery.
- Insufficient evidence to publish a reviewed discovery.

### Apollo Hospitals Enterprise
Run `run-94ca3c9301`; failed.
- Search unavailable for site:apolloendo.com Apollo Endosurgery, Inc. annual report consolidated financial statements filetype:pdf: Account-free search unavailable (DDGSException); it may be rate-limited. Retry later or use another provider.. Coverage is incomplete.
- Search unavailable for site:apolloendo.com Apollo Endosurgery, Inc. quarterly results revenue segment presentation filetype:pdf: Account-free search unavailable (DDGSException); it may be rate-limited. Retry later or use another provider.. Coverage is incomplete.
- Insufficient financial evidence to form a hypothesis: recent comparable, anchored financial numbers and a valid relationship are required. Scheduling notices do not establish a financial discovery.
- Insufficient evidence to publish a reviewed discovery.
- Resolved entity does not match all distinctive words of the requested company; all interpretations withheld.

### Max Healthcare Institute
Run `run-68e504107e`; failed.
Company identity needs verification: Company identity quotes could not be matched to a source name and ticker. The checkpoint is saved.
- Publication dates may be unknown. This is current public-source research, not a point-in-time backtest.
- Could not collect https://financialfilings.com/companies/max-healthcare-institute-limited/: ValueError: Source retrieval failed (HTTP 403).
- Could not collect https://www.maxhealthcare.in/investors: ValueError: Source retrieval failed (HTTP 403).
- Could not collect https://www.maxhealthcare.in/financials: ValueError: Source retrieval failed (HTTP 403).
- Company identity quotes could not be matched to a source name and ticker.

### Divi's Laboratories
Run `run-c5b7316ca5`; insufficient_evidence.
Withheld: Unresolved hypothesis: Divi's Laboratories demonstrated stronger growth in profit after tax (18.02% using calc-pat-growth) compared to total revenue from operations (12.94% using calc-rev-growth) for FY2026.
- The discovery is not corroborated by at least two source documents.
- No subsidiaries or facilities were explicitly named with supporting location or entity names in the provided text snippet.
- Could not collect https://www.divislabs.com/wp-content/uploads/2025/07/34.-Update-on-WaringLetter.pdf: ValueError: PDF could not be parsed; the original download remains archived.
- Search unavailable for Divi's Laboratories Divi's Laboratories annual report custom synthesis API revenue concentration: Account-free search unavailable (DDGSException); it may be rate-limited. Retry later or use another provider.. Coverage is incomplete.
- Search unavailable for Divi's Laboratories Divi's Laboratories geographic segment revenue export percentage: Account-free search unavailable (DDGSException); it may be rate-limited. Retry later or use another provider.. Coverage is incomplete.
- Rejected skeptic review with unknown hypothesis or evidence IDs.

## Demo selection

No finding qualified for a supported/unresolved demo under the publication policy. The [real walkthrough](REAL_CASE.md) therefore documents the strongest evidence-bearing research attempt, Sun Pharma, with an explicit no-discovery status. It is not a substitute successful finding.

Machine-readable outcomes, source URLs, run IDs, limits and warnings are in [EVALUATION.json](EVALUATION.json). Company names are evaluation inputs; financial stories are not hardcoded.
