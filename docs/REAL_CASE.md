# Real research walkthrough: Sun Pharma

**Status: no published discovery. The retained hypothesis is unresolved; no finding qualified for a supported or unresolved demo.**

Run `run-588a851a3d`. The cycle took 197.09 seconds and retained 27 financial inputs. These are extraction/runtime observations, not proof of a novel insight.

## What the agent established

The cited consolidated income statement reports revenue from operations of INR 525,784.4 million for FY2025 and INR 584,620.4 million for FY2026. The checked change is 11.190138%. Both values, their year-column assignment and the million-unit label were visually checked against the original PDF page.

The source is the [Sun Pharma annual report 2025-26](https://sunpharma.com/wp-content/uploads/2026/07/Sun-Pharma_AR-2025-26.pdf#page=242), physical PDF page 242 (printed page 240). Publication date is not separately verified; the URL date is not used as proof of publication timing.

## Calculation
- Determine the precise annual growth rate of revenue from operations between FY2025 and FY2026.
- Formula: `(second / first - 1) * 100`.
- Result: **11.190138 %**.
- Inputs in base currency units: ['525784400000.0', '584620400000.0']; periods ['FY2025', 'FY2026'].

## Hypothesis the agent tested

The acceleration in revenue from operations from FY2025 to FY2026 reflects a structural shift in core pharmaceutical sales rather than one-off other income items.

This proposed structural explanation goes beyond observing revenue growth. It was not established as a causal or non-obvious finding.

## Evidence trail

### fact-06bea2667765: Revenue from operations / FY2026
Value 584620.4 INR million; basis consolidated; physical page 242.
[Original document](https://sunpharma.com/wp-content/uploads/2026/07/Sun-Pharma_AR-2025-26.pdf)

> (I)  Revenue from operations                                                  30           584,620.4        525,784.4

Column header:

> Year ended         Year ended Particulars                                                                              Notes                                                                                           March 31, 2026    March 31, 2025

Separate context, physical page 242:

> ₹ in Million

### fact-222990aa47ec: Revenue from operations / FY2025
Value 525784.4 INR million; basis consolidated; physical page 242.
[Original document](https://sunpharma.com/wp-content/uploads/2026/07/Sun-Pharma_AR-2025-26.pdf)

> (I)  Revenue from operations                                                  30           584,620.4        525,784.4

Column header:

> Year ended         Year ended Particulars                                                                              Notes                                                                                           March 31, 2026    March 31, 2025

Separate context, physical page 242:

> ₹ in Million

### fact-a28180523ad8: Total income / FY2026
Value 604337.6 INR million; basis consolidated; physical page 242.
[Original document](https://sunpharma.com/wp-content/uploads/2026/07/Sun-Pharma_AR-2025-26.pdf)

> (III) Total income (I + II)                                                                            604,337.6        545,434.8

Column header:

> Year ended         Year ended Particulars                                                                              Notes                                                                                           March 31, 2026    March 31, 2025

Separate context, physical page 242:

> ₹ in Million

### fact-b40689453812: Total income / FY2025
Value 545434.8 INR million; basis consolidated; physical page 242.
[Original document](https://sunpharma.com/wp-content/uploads/2026/07/Sun-Pharma_AR-2025-26.pdf)

> (III) Total income (I + II)                                                                            604,337.6        545,434.8

Column header:

> Year ended         Year ended Particulars                                                                              Notes                                                                                           March 31, 2026    March 31, 2025

Separate context, physical page 242:

> ₹ in Million

## Timeline

- FY2025 and FY2026 are the reported fiscal endpoints in the cited table.
- The evidence does not locate a structural business-model change within that interval.

## Counterargument and missing tests

The top-line growth could be driven by foreign exchange movements, non-recurring licensing income, or newly consolidated subsidiaries rather than sustainable organic expansion of core pharmaceutical sales.

While consolidated revenue from operations expanded from 525,784.4 Million INR in FY2025 to 584,620.4 Million INR in FY2026, the available facts do not yet rule out foreign exchange impacts or inorganic contributions from acquisitions. Therefore, the hypothesis remains unresolved.

The cited revenue and total-income measurements come from the same issuer income statement. They do not independently establish organic growth, exclude acquisitions/currency effects, or prove a shift in the business model.

## Proposed future test

{
  "metric": "organic revenue growth percentage",
  "comparison": "at_least",
  "threshold": "8",
  "window_start": "2026-10-25",
  "window_end": "2027-09-30",
  "source": "Sun Pharmaceutical Industries Limited Annual Report"
}

This is the agent's proposed test, not future evidence already observed and not a validated causal threshold.

## What was withheld

The structural-shift explanation was not published. The skeptic verdict remained unresolved and composition emitted no final discovery. Earlier malformed falsification formatting was rejected and repaired; that does not resolve the substantive evidence gaps.

## Evidence strength

No final Strong/Moderate/Weak finding rating was emitted. The underlying table observation is auditable, but independent support and the proposed driver remain insufficient. Do not label this attempt a supported discovery.

## Reproduce and inspect

Start the dashboard from the project folder and select the Sun Pharmaceutical Industries run with the ID above. Export that selected run for the complete saved evidence record. The full batch and failures are in [EVALUATION.md](EVALUATION.md).
