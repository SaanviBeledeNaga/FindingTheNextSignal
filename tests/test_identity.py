from copy import deepcopy
import pytest

from pharma_scope.evidence import anchored_identity


def profile():
    return {"name": "Example Ltd.", "symbol": "EXAMPLE.NS", "official_domain": "example.test", "aliases": [],
            "subsidiaries": [], "facilities": [], "competitors": [], "uncertainty": [],
            "identity_evidence": [{"url": "https://disclosures.test/example", "quote": "EXAMPLE LTD."}]}


def sources():
    return [{"url": "https://disclosures.test/example", "pages": ["Annual reports\nEXAMPLE LTD.\nExample Ltd.\nEXAMPLE.NS\nIndia\nPharmaceuticals"]}]


def test_short_company_label_is_valid_with_grounded_name_and_ticker():
    result = anchored_identity(profile(), "EXAMPLE", sources())
    assert result["identity_evidence"][0]["quote"] == "EXAMPLE LTD."
    assert result["official_domain"] == ""
    assert any("inferred domain omitted" in warning for warning in result["uncertainty"])


def test_short_label_without_matching_ticker_is_not_enough():
    value = profile()
    value["symbol"] = "INVENTED"
    with pytest.raises(ValueError, match="quotes"):
        anchored_identity(value, "EXAMPLE", sources())


def test_invented_quote_still_rejected():
    value = profile()
    value["identity_evidence"][0]["quote"] = "Example makes oncology drugs across 50 countries."
    with pytest.raises(ValueError):
        anchored_identity(value, "EXAMPLE", sources())


def test_unrelated_company_is_rejected():
    with pytest.raises(ValueError, match="requested"):
        anchored_identity(profile(), "UNRELATED", sources())


def test_explicit_domain_is_preserved():
    evidence = sources()
    evidence[0]["pages"][0] += "\nWebsite: https://example.test"
    assert anchored_identity(profile(), "EXAMPLE", evidence)["official_domain"] == "example.test"
