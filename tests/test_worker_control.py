"""Operator CLI failures remain content-free and independent of API settings."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import worker_control as cli
from app.services.worker_drain_service import ControlError


@pytest.mark.parametrize("error", [
    ValueError("SECRET postgresql://user:password@example"),
    RuntimeError("SECRET prompt"), TimeoutError("SECRET"),
])
def test_cli_redacts_database_and_driver_failures(monkeypatch, capsys, error):
    monkeypatch.setattr(cli, "run", AsyncMock(side_effect=error))
    assert cli.main(["pause"]) == 2
    captured = capsys.readouterr()
    assert not captured.out
    assert json.loads(captured.err)["error"] == "control unavailable"
    assert "SECRET" not in captured.err and "password" not in captured.err


def test_cli_missing_dedicated_credentials_fails_closed(monkeypatch, capsys):
    monkeypatch.delenv("WORKER_DRAIN_DATABASE_URL", raising=False)
    # App DATABASE_URL is deliberately not a fallback for operator credentials.
    monkeypatch.setenv("DATABASE_URL", "SECRET")
    assert cli.main(["status", "--require-drained"]) == 2
    assert json.loads(capsys.readouterr().err)["error"] == "WORKER_DRAIN_DATABASE_URL is required"


def test_cli_safe_metadata_and_predicate_errors(monkeypatch, capsys):
    result = {"schema_version": "worker_drain.v1", "epoch": 7, "admission": "paused"}
    run = AsyncMock(return_value=result)
    monkeypatch.setattr(cli, "run", run)
    assert cli.main(["status", "--expect-epoch", "7", "--require-drained"]) == 0
    assert json.loads(capsys.readouterr().out) == result
    args = run.call_args.args[0]
    assert args.expect_epoch == 7 and args.require_drained
    run.side_effect = ControlError("workers are not drained")
    assert cli.main(["status", "--require-drained"]) == 2
    assert json.loads(capsys.readouterr().err)["error"] == "workers are not drained"


@pytest.mark.parametrize("argv", [
    ["pause", "--require-drained"], ["resume", "--require-drained"],
    ["status", "--expect-epoch", "-1"], ["status", "--expect-epoch", "nan"],
])
def test_invalid_cli_predicates_fail_before_connection(monkeypatch, argv):
    run = AsyncMock()
    monkeypatch.setattr(cli, "run", run)
    with pytest.raises(SystemExit) as failure:
        cli.main(argv)
    assert failure.value.code == 2
    run.assert_not_awaited()


def test_cli_require_drained_dispatches_to_live_status(monkeypatch):
    control = SimpleNamespace(status=AsyncMock(return_value={"drained": True}))
    monkeypatch.setattr(cli, "WorkerDrainControl", lambda sessions: control)
    args = cli.parser().parse_args(["status", "--expect-epoch", "9", "--require-drained"])
    assert asyncio.run(cli.execute(args, object())) == {"drained": True}
    control.status.assert_awaited_once_with(expected_epoch=9, require_drained=True)
