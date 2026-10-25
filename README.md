# Pharma Scope

Autonomous public-source financial research for pharma and healthcare companies. The application collects evidence, calculates relationships, forms and challenges hypotheses, and withholds unsupported conclusions.

## Read the right document

- [Two-page overview](docs/OVERVIEW.pdf): problem, pipeline, live evaluation and limits.
- [Overview source](docs/OVERVIEW.md): the editable overview.
- [Runbook](docs/RUNBOOK.md): installation, API settings, dashboard, resume and export commands.
- [Technical appendix](docs/APPENDIX.md): evidence rules, statuses, budgets and storage.
- [Live evaluation](docs/EVALUATION.md) and [real company walkthrough](docs/REAL_CASE.md): actual results, including failed or withheld outcomes.
- [Requirements assessment](REQUIREMENTS.md): what remains incomplete against the brief.

## Start locally

Open a terminal in the project directory:

```powershell
python -m pip install -e ".[ai,search]"
python -m pharma_scope doctor
python -m pharma_scope web --open
```

Configure the existing local `.env` first using the runbook. Keep keys and `.pharma` out of GitHub. The dashboard runs at [localhost](http://127.0.0.1:8765/); searches and model requests use the internet.

## Bounded 270s cycle

Standard and Wider use the same research budget. Wider allows greater source/page/model coverage, not more time. A supervisor stops a stalled dashboard worker at 280s; saving and display can add overhead. A cycle is not a guarantee of a complete investigation, sufficient data or a supported discovery.

## Research status

The workflow, local dashboard, numeric validation, calculations, claim audit, exports and dated official eligibility snapshot are implemented. Novel discovery across unseen companies, complete five-year drivers, broad independent corroboration, scanned-document OCR and before-mainstream-coverage timing remain incomplete or unproven. Read the evaluation and evidence trail instead of inferring research quality from software test counts.
