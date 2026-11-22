import json
from pathlib import Path

import pytest

from app.services.email_identity import normalize_email

CASES = json.loads((Path(__file__).parent / "fixtures/web_sessions/email-identity.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES["canonical"])
def test_preserves_address_structure_and_normalizes_ascii_case(case):
    subject = normalize_email(case["input"])
    assert subject == case["subject"]
    assert normalize_email(subject) == subject


@pytest.mark.parametrize("value", CASES["rejected"])
def test_rejects_ambiguous_or_unsupported_addresses_without_echoing(value):
    with pytest.raises(ValueError) as error:
        normalize_email(value)
    assert str(error.value) == "invalid email address"


def test_email_length_limits():
    with pytest.raises(ValueError):
        normalize_email("x" * 65 + "@example.com")
    with pytest.raises(ValueError):
        normalize_email("x@" + ".".join(["y" * 63] * 4))
