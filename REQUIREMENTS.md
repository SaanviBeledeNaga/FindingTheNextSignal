# Audit against the supplied Track D brief

Assessment: **partially compliant; not yet demonstrated as finals-ready.** The research graph implements the required workflow, but implementation alone does not establish discovery quality, novelty or generality. This assessment uses the supplied brief, current code and actual saved investigations; it does not assert independently verified present-day NIFTY membership.

## Research workflow

| Requirement | Assessment | Evidence and remaining limitation |
|---|---|---|
| Discover angles autonomously | Implemented | `agent.resolve`, `plan`, `gather`; model-selected questions and public searches, without preset company results. |
| Connect multiple kinds of public evidence | Partial | Archived documents and fact IDs connect filings and other sources. Competitor/industry coverage and credible-news corroboration remain inconsistent. |
| Calculate relationships | Implemented | `evidence.calculation` checks shares, margins, growth, differences and CAGR with Decimal. Dedicated working-capital metrics such as receivable days are not yet provided. |
| Form and test hypotheses | Implemented | `hypothesize`, `followup`, `skeptic`, `compose`; bounded repair attempts retain strict evidence validation. |
| Seek contradictions and alternatives | Partial | Follow-up queries and alternative tests exist, but retrieval failures and limits can leave questions unresolved. |
| Prove conclusions with an audit trail | Partial | Exact quotations, original links, physical pages, table context, hashes and calculation inputs are exposed. Semantic support and column attribution remain fallible. |

## Eight required output elements

| Element | Assessment |
|---|---|
| One clear, non-obvious discovery sentence | Schema/rendering implemented; supported non-obvious discovery remains unproven in live trials. |
| Three to five significance bullets | Enforced by validation; each bullet needs citations. |
| Multiple independent linked sources | Publication gate exists, but independence is conservatively established only for certain issuer/regulator origins. Repeated documents are not independent. News, competitors and industry corroboration need better verification. |
| Timeline | Cited exact dates or fiscal periods required; no invented quarter-to-calendar dates. |
| Necessary financial numbers/calculations | Valid calculations and their actual input facts required; incompatible scopes/definitions are checked. |
| Strongest counterargument | Required in the finding schema and shown alongside alternative tests. Quality depends on available evidence. |
| Future falsification condition | Metric, finite numerical threshold, future observation window and expected public source required. This is a proposed test, not observed evidence. |
| Strong/Moderate/Weak with reasons | Deterministic rating and rationale implemented; a rating is not a probability of truth. |

## Track D and judging criteria

| Criterion | Assessment |
|---|---|
| Business-model drift toward specialty/CDMO/domestic formulations | Supported as a research angle; reliably corroborated mix-change discovery and timing have not been demonstrated. |
| Regulatory effects in financials before mainstream coverage | Regulatory evidence and chronological checks exist. Systematic first-mainstream-coverage timestamp comparison is missing. |
| Five-year geographic exposure and drivers | Geographic extraction and offline share-change analysis exist. Complete five-year live coverage, comparable regional classifications and independently tested drivers remain incomplete. |
| Discovery quality and novelty | Unproven. A conventional ratio comparison is not automatically a hidden financial story; there is no independent novelty benchmark. |
| Temporal reasoning | Partial. Fiscal/date anchoring exists; causal ordering and event-to-financial effects remain dependent on available dated evidence. |
| Cross-source reasoning and robustness | Partial. The graph connects sources and tests alternatives, but trials still produce unresolved findings. |
| Falsifiability and explainability | Output support implemented; the new web dashboard exposes the calculation and passage trail directly. |
| Any unseen NIFTY 50 company in the track | Unproven. Parameterized code supports arbitrary names; broad live evaluation, A dated official constituent snapshot now checks membership and Healthcare industry; live/historical eligibility remains unverified. |
| Other listed sector companies in a tie-break | Input support exists; reliable live performance has not been established. |

## What actual saved research shows

The latest Sun Pharma record has 39 retained source-anchored facts, 30 financial inputs, one unresolved finding and no supported discovery. The finding compares FY2020–FY2021 inventory growth with revenue growth. Inventory facts are labelled standalone, while revenue facts are consolidated, but the discovery sentence does not distinguish the reporting scopes. This is a material internal comparability issue. It must not be presented as a validated financial interpretation.

Version 0.5.0 exposes that conflict in the dashboard and completion checks and rejects new claim/timeline text that silently mixes or contradicts those scopes. This is an internal consistency check; it does not independently prove that the original source tables were interpreted correctly. The historical archive is retained rather than rewritten to manufacture compliance.

Other actual trials on Cipla and Dr. Reddy's have not demonstrated supported discoveries. Synthetic demo outputs demonstrate interface behavior only. Passing software tests does not establish the fictional demo as real-company evidence or prove generality.

## Ground rules

The supplied collectors use public HTTP(S) sources and search leads. No proprietary financial database is required. Company-specific discoveries are not hardcoded. Major finding claims require citations, and the output schema does not request investment recommendations. Team originality and compliance with submission rules require a human review; the application cannot certify them.

## Remaining work before a confident finals claim

1. Demonstrate a supported non-obvious discovery on multiple unseen companies using the same unmodified system.
2. Improve retrieval and independent-origin verification for competitor, industry and credible-news evidence.
3. Check table scope, columns, units, fiscal periods and restatements against source layouts; the current text/model checks are not enough to guarantee accuracy.
4. Implement explicit mainstream-coverage chronology for any before-news regulatory claim.
5. Establish comparable five-year geographic coverage and test alternative drivers, rather than assuming a causal explanation.
6. Maintain the dated official membership/industry snapshot and review the reproducible live evaluation outcomes. Novelty and evidence quality need human adjudication, not a fabricated confidence percentage.

## Review changes

Multi-value table facts now have a required dedicated column-header field, checked against the source row and actual year/value order. Financial statement pages receive priority layout reconstruction, including cached-PDF refresh. This does not establish perfect table interpretation.

A static official 50-company snapshot and Healthcare classification check are implemented with source URL, retrieval timestamp and hash; effective date is unknown. This is not a live or historical membership service. Other-sector members are outside Track D; nonmembers remain extended-universe cases with sector eligibility unverified.

See `docs/EVALUATION.md` for the complete live batch and `docs/REAL_CASE.md` for the strongest qualifying real case. Failed or withheld outcomes remain failures; unresolved hypotheses are not promoted to supported discoveries.
