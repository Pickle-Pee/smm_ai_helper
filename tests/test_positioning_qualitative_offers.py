"""Offer synthesis retains fulfillment conditions and existing quantity truth rules."""
from dataclasses import replace
from unittest.mock import Mock

import pytest

from app.module_execution.executors import ExecutorOutputError
from app.module_execution.executors.common import OutputFailureStage
from app.module_registry import ModuleId
from tests.test_module_executors import FakeModel, dispatch, request


SUPPLIED_TRUTH = "Занятие проходит с сопровождением мастера; изделие можно получить после обжига."
UNQUANTIFIED_OFFER = "Вводное занятие с сопровождением мастера и получением изделия после обжига."
ONE_VISIT_OFFER = "Одно посещение с сопровождением мастера и получением изделия после обжига."


def offer_request(truth=SUPPLIED_TRUTH):
    invocation = request(ModuleId.POSITIONING, outputs=("offer",))
    return replace(invocation, context_packet=replace(invocation.context_packet,
        known_facts=tuple(replace(fact, value=truth) if fact.label == "product_truth" else fact
                          for fact in invocation.context_packet.known_facts)))


def offer_model(text):
    def propose(payload, data):
        truth = next(e for e in data["local_evidence"] if e["input_key"] == "product_truth")
        payload["outputs"][0].update(text=text, kind="RECOMMENDATION", evidence_ids=[truth["evidence_id"]])
    return FakeModel(propose)


def test_one_visit_offer_is_rejected_even_with_correct_delayed_fulfillment(monkeypatch):
    from app.module_execution.executors.common import log
    warning = Mock()
    monkeypatch.setattr(log, "warning", warning)
    model = offer_model(ONE_VISIT_OFFER)
    with pytest.raises(ExecutorOutputError) as caught:
        dispatch(offer_request(), model)
    assert caught.value.stage is OutputFailureStage.STATEMENT_SEMANTICS_INVALID
    warning.assert_called_once_with("Module output rejected module=%s stage=%s rule=%s",
        "POSITIONING", "statement_semantics_invalid", "numerical_support_required")
    assert "после обжига" in ONE_VISIT_OFFER and len(model.calls) == 1


def test_unquantified_synthesized_offer_with_same_fulfillment_remains_allowed():
    assert UNQUANTIFIED_OFFER not in SUPPLIED_TRUTH
    model = offer_model(UNQUANTIFIED_OFFER)
    result = dispatch(offer_request(), model)
    assert result.payload["outputs"][0]["text"] == UNQUANTIFIED_OFFER
    assert result.normalized_result.claims[0].value == UNQUANTIFIED_OFFER
    assert "после обжига" in result.payload["outputs"][0]["text"]
    assert len(model.calls) == 1


def test_whole_one_visit_offer_verbatim_from_actual_cited_truth_remains_allowed():
    model = offer_model(ONE_VISIT_OFFER)
    result = dispatch(offer_request(ONE_VISIT_OFFER), model)
    assert result.payload["outputs"][0]["text"] == ONE_VISIT_OFFER
    assert result.payload["outputs"][0]["evidence_ids"] == result.normalized_result.claims[0].evidence_ids
    assert result.schema_version == "positioning.payload.v1" and len(model.calls) == 1
