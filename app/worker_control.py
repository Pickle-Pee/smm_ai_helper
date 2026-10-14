"""Operator-only CLI. Credentials come from a dedicated environment variable.

python -m app.worker_control pause|status|resume [--expect-epoch N]
Access is enforced by host access and PostgreSQL role grants, not an HTTP token.
"""
import argparse
import asyncio
import json
import os
import sys

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.services.worker_drain_service import ControlError, WorkerDrainControl


def epoch(value):
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("epoch must be nonnegative")
    return number


def parser():
    result = argparse.ArgumentParser(description="PostgreSQL worker drain control")
    result.add_argument("action", choices=("pause", "status", "resume"))
    result.add_argument("--expect-epoch", type=epoch)
    result.add_argument("--require-drained", action="store_true",
                        help="status fails unless admission is paused and all attempts have released claims")
    return result


async def execute(args, sessions):
    control = WorkerDrainControl(sessions)
    if args.action == "status":
        return await control.status(expected_epoch=args.expect_epoch, require_drained=args.require_drained)
    return await getattr(control, args.action)(expected_epoch=args.expect_epoch)


async def run(args):
    raw = os.environ.get("WORKER_DRAIN_DATABASE_URL")
    if not raw:
        raise ControlError("WORKER_DRAIN_DATABASE_URL is required")
    url = make_url(raw)
    if url.drivername != "postgresql+asyncpg":
        raise ControlError("operator connection requires postgresql+asyncpg")
    engine = create_async_engine(url, echo=False, hide_parameters=True)
    try:
        async with asyncio.timeout(15):
            return await execute(args, async_sessionmaker(engine, expire_on_commit=False))
    finally:
        await engine.dispose()


def main(argv=None):
    arg_parser = parser()
    args = arg_parser.parse_args(argv)
    if args.require_drained and args.action != "status":
        arg_parser.error("--require-drained applies only to status")
    try:
        result = asyncio.run(run(args))
    except Exception as exc:
        # Never print driver exceptions, SQL, connection URLs or credential values.
        error = str(exc) if isinstance(exc, ControlError) else "control unavailable"
        print(json.dumps({"error": error, "error_type": type(exc).__name__}), file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
