"""Hydration rechecks every semantic trust boundary without provider calls."""
import copy
import hashlib

import pytest

from app.marketing_copilot.context_projection import (
    BusinessFactCandidate, InterpretedRequest, NaturalLanguageContextProjection,
)
from app.marketing_copilot.contracts import CopilotContractError, IntentKind
from app.marketing_copilot.interpretation_store import message_fingerprint, validate_interpretation
from tests.test_marketing_copilot import intent

MESSAGE = "Build a strategy for a kindergarten https://example.com"


def interpretation(kind=IntentKind.MARKETING_STRATEGY):
    return InterpretedRequest(intent=intent(kind, provided_urls=("https://example.com",)),
        projection=NaturalLanguageContextProjection(facts=(BusinessFactCandidate(
            key="product", value="kindergarten"),)))


def test_exact_utf8_fingerprint_and_strict_roundtrip():
    assert message_fingerprint(MESSAGE) == hashlib.sha256(MESSAGE.encode("utf-8")).hexdigest()
    assert message_fingerprint(MESSAGE) != message_fingerprint(MESSAGE + " ")
    value = interpretation()
    assert validate_interpretation(value.model_dump(mode="json"), MESSAGE) == value


@pytest.mark.parametrize("corruption", ["enum", "type", "duplicate", "projection", "url", "source", "authority"])
def test_corruption_fails_closed(corruption):
    raw = copy.deepcopy(interpretation().model_dump(mode="json"))
    if corruption == "enum":
        raw["intent"]["kind"] = "unknown"
    elif corruption == "type":
        raw["intent"]["confidence"] = "0.9"
    elif corruption == "duplicate":
        raw["projection"]["facts"] *= 2
    elif corruption == "projection":
        raw["projection"]["facts"][0]["value"] = "invented paraphrase"
    elif corruption == "url":
        raw["intent"]["provided_urls"] = ["https://invented.example"]
    elif corruption == "source":
        raw["intent"]["source_references"] = ["invented source"]
    else:
        raw["executor"] = "execute"
    with pytest.raises(CopilotContractError, match="Invalid persisted"):
        validate_interpretation(raw, MESSAGE)


def test_core_revalidates_internal_interpretation_before_execution():
    import asyncio
    from unittest.mock import Mock
    from app.marketing_copilot.application_contracts import CopilotRequest
    from tests.test_copilot_application import service

    original = interpretation(IntentKind.COMPETITOR_ANALYSIS)
    corrupt = original.model_copy(update={"intent": original.intent.model_copy(
        update={"provided_urls": ("https://invented.example",)})})
    copilot = service(IntentKind.COMPETITOR_ANALYSIS)
    copilot.policy.decide = Mock()
    with pytest.raises(CopilotContractError):
        asyncio.run(copilot.execute(CopilotRequest(actor_id=1, request_id="r", message=MESSAGE),
                                   interpreted=corrupt))
    copilot.policy.decide.assert_not_called()
