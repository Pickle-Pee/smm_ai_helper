from app.services.facts_extractor import FACTS_TEMPLATE, FactsPayload


def test_facts_schema_validation():
    payload = {
        "facts": FACTS_TEMPLATE,
        "conflicts": [],
    }
    validated = FactsPayload(**payload)
    for key in FACTS_TEMPLATE.keys():
        assert key in validated.facts
