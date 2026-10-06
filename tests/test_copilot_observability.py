import asyncio

import pytest

from app.marketing_copilot.observability import stage_timing


@pytest.mark.parametrize("failure", [None, TimeoutError("PRIVATE PAYLOAD"), asyncio.CancelledError("PRIVATE PAYLOAD")])
def test_stage_uses_monotonic_time_and_preserves_failures(monkeypatch, caplog, failure):
    clock = iter((10.0, 10.25))
    monkeypatch.setattr("app.marketing_copilot.observability.time.monotonic", lambda: next(clock))
    with caplog.at_level("INFO", logger="app.marketing_copilot.observability"):
        def execute():
            with stage_timing("owned_acquisition", request_key="r1", user_id=7):
                if failure is not None:
                    raise failure
        if failure is None:
            execute()
        else:
            with pytest.raises(type(failure)) as error:
                execute()
            assert error.value is failure
    record, = caplog.records
    assert record.args == ("owned_acquisition", 250, "r1", 7,
                           "failed" if failure else "success", type(failure).__name__ if failure else None)
    assert "PRIVATE" not in caplog.text
