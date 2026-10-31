"""Diagnostic-only regression: statement location, closed categories and privacy."""
from dataclasses import replace
import logging
import traceback

import pytest

from app.module_execution.executors import ExecutorOutputError, PositioningExecutor
from app.module_execution.executors.common import (
    BaseExecutor, StatementSemanticsError, first_party_evidence, scoped_facts, log, plain,
)
from app.module_execution.executors.provider_schema import schema_measurement
from app.module_execution.executors.schemas import PositioningOutput
from app.module_registry import ModuleId
from tests.test_module_executors import FakeModel, dispatch, fact, request


@pytest.mark.parametrize("index", [0, 1, 2, 3])
@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("category", ["product", "target_or_target_hypothesis", "private_label"])
def test_semantic_diagnostic_location_categories_privacy(index, reverse, category, caplog, monkeypatch):
    monkeypatch.setattr(log, "disabled", False)
    caplog.set_level(logging.INFO, logger=log.name)
    names = ["RTB", "value_proposition", "positioning_statement", "offer"]
    req = request(ModuleId.POSITIONING, outputs=tuple(names), identity="job.test:123")
    if reverse:
        names.reverse()
    facts = (*req.context_packet.known_facts, fact("private_label", "PRIVATE_FACT"))
    facts = tuple(replace(item, value="PRIVATE_FACT", source="PRIVATE_SOURCE") for item in facts)
    req = replace(req, objective="PRIVATE_OBJECTIVE",
                  context_packet=replace(req.context_packet, known_facts=facts))

    def reject(payload, data):
        if reverse:
            payload["outputs"].reverse()
        payload["outputs"][index].update(text="PRIVATE_CLAIM", evidence_ids=[
            next(e["evidence_id"] for e in data["local_evidence"] if e["input_key"] == category)])

    model = FakeModel(reject)
    with pytest.raises(ExecutorOutputError) as caught:
        dispatch(req, model)
    records = [r for r in caplog.records if r.msg.startswith("Module statement diagnostic")]
    assert len(records) == 1
    record = records[0]
    assert record.output_index == index
    assert record.output_name == names[index]
    assert record.kind == "HYPOTHESIS"
    assert record.evidence_categories == [category if category != "private_label" else "other"]
    assert record.execution_id == req.execution_id
    assert record.validation_schema_sha256 != record.provider_schema_sha256
    assert record.provider_schema_sha256 == schema_measurement(model.calls[0]["response_schema"])["sha256"]
    assert caught.value.stage.value == "statement_semantics_invalid"
    assert type(caught.value) is ExecutorOutputError
    assert len(model.calls) == 1
    exposed = caplog.text + repr(record.__dict__) + "".join(traceback.format_exception(caught.value))
    for sentinel in ("private_label", "PRIVATE_FACT", "PRIVATE_SOURCE", "PRIVATE_OBJECTIVE", "PRIVATE_CLAIM"):
        assert sentinel not in exposed
    assert "evd_" not in exposed


def test_internal_semantic_exception_keeps_metadata():
    req = request(ModuleId.POSITIONING, outputs=("target", "RTB"))
    evidence = first_party_evidence(req, scoped_facts(req))
    model = FakeModel()
    result = dispatch(req, model)
    payload = plain(result.payload)
    payload["outputs"][1]["evidence_ids"] = [evidence[0].record.evidence_id]
    output = PositioningOutput.model_validate(payload)
    with pytest.raises(StatementSemanticsError) as caught:
        BaseExecutor.build_result(PositioningExecutor(model_call=None), req, output, evidence, {})
    assert caught.value.output_index == 1
    assert caught.value.statement_metadata == {
        "output_index": 1, "output_name": "RTB", "kind": "HYPOTHESIS", "evidence_categories": ["product"],
    }
