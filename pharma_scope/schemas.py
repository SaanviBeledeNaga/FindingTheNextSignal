"""Closed schemas shared by both model providers and local validation."""
S = {"type": "string"}
I = {"type": "integer"}
B = {"type": "boolean"}


def arr(item):
    return {"type": "array", "items": item}


def obj(**fields):
    return {"type": "object", "properties": fields, "required": list(fields), "additionalProperties": False}


def enum(*values):
    return {"type": "string", "enum": list(values)}


PROFILE = obj(name=S, symbol=S, official_domain=S, aliases=arr(S), subsidiaries=arr(S), facilities=arr(S),
              identity_evidence=arr(obj(url=S, quote=S)), competitors=arr(S), uncertainty=arr(S))
PLAN = obj(angles=arr(obj(angle=enum("geography", "business_model", "regulatory"), question=S,
                           significance=S, queries=arr(S))), identity_notes=arr(S))
FACT = obj(kind=enum("financial", "business", "regulatory", "industry", "management"), statement=S,
           page=I, quote=S, event_date=S, fiscal_period=S, metric=S, value=S, currency=S, unit=S,
           basis=S, definition=S, entity=S, context_evidence=arr(obj(page=I, quote=S)))
FACTS = obj(facts=arr(FACT), publication_date=S, origin_group=S,
            source_kind=enum("issuer", "regulator", "competitor", "industry", "news", "other"),
            geography_observations=arr(obj(period=I, region=S, value=S, currency=S, unit=S, basis=S,
                                           definition=S, page=I, quote=S)))
CALC = obj(id=S, operation=enum("share", "growth_pct", "difference", "margin_pct", "cagr_pct"),
           inputs=arr(S), years=I, purpose=S)
HYPOTHESIS = obj(id=S, angle=enum("geography", "business_model", "regulatory"), hypothesis=S,
                 financial_significance=S, supporting_facts=arr(S), opposing_facts=arr(S),
                 alternative_explanations=arr(S), calculations=arr(CALC), followup_queries=arr(S))
HYPOTHESES = obj(hypotheses=arr(HYPOTHESIS))
FUTURE_TEST = obj(metric=S, comparison=enum("above", "below", "at_least", "at_most"), threshold=S,
                  window_start=S, window_end=S, source=S)
SKEPTIC = obj(reviews=arr(obj(hypothesis_id=S, verdict=enum("supported", "unresolved", "rejected"),
    strongest_counterargument=S, supporting_facts=arr(S), opposing_facts=arr(S),
    alternative_tests=arr(obj(explanation=S, outcome=enum("ruled_out", "unresolved", "supported"), evidence=arr(S))),
    cause_precedes_effect=B, chronology_evidence=arr(S), causal_claim=B,
    falsification_condition=S, future_test=FUTURE_TEST, followup_queries=arr(S), reasoning=S)))
CLAIM_AUDIT = obj(reviews=arr(obj(hypothesis_id=S, all_claims_supported=B, track_relevant=B,
    unsupported_claims=arr(S), reasoning=S)))
CLAIM = obj(text=S, evidence=arr(S), calculations=arr(S))
FINDINGS = obj(findings=arr(obj(hypothesis_id=S, discovery=CLAIM, why_it_matters=arr(CLAIM),
    timeline=arr(obj(date=S, description=S, evidence=arr(S))), supporting_facts=arr(S), opposing_facts=arr(S),
    counterargument=CLAIM, falsification_condition=S, conclusion=enum("supported", "unresolved", "rejected"),
    limitations=arr(S))))
