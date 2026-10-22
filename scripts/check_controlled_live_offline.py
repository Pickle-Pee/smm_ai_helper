"""Reproduce controlled-live regression with fake settings and no external sockets.

Run from the repository root. Never supply disposable/live service credentials to
this runner: it intentionally unsets them. Real PostgreSQL/Redis checks are a
separate operator gate using ordinary pytest and explicitly disposable services.
"""
import argparse
import ipaddress
import os
from pathlib import Path
import socket
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    candidate = Path(__file__).resolve().parents[1]
    os.chdir(candidate)
    for key in list(os.environ):
        if any(name in key for name in ("OPENAI", "TELEGRAM", "DATABASE", "REDIS", "BOT_BACKEND",
                                       "API_BASE_URL", "CONTROLLED_LIVE", "DEPLOYMENT_ENVIRONMENT")):
            os.environ.pop(key, None)
    os.environ.update(
        DATABASE_URL="postgresql+asyncpg://offline:offline@127.0.0.1:1/smm_mvp_test_offline",
        TELEGRAM_BOT_TOKEN="123456:offline-only", OPENAI_API_KEY="offline-not-a-key",
        BOT_BACKEND_TOKEN="offline-service-only", OPENAI_BASE_URL="http://127.0.0.1:1/v1",
        REDIS_URL="redis://127.0.0.1:1/15", API_BASE_URL="http://127.0.0.1:1",
        CONTROLLED_LIVE_ENABLED="false",
    )
    sys.path.insert(0, str(candidate))

    def guarded(original):
        def connect(sock, address):
            try:
                allowed = ipaddress.ip_address(address[0]).is_loopback
            except (ValueError, TypeError, IndexError):
                allowed = False
            if not allowed:
                raise RuntimeError("External network disabled for regression")
            return original(sock, address)
        return connect

    socket.socket.connect = guarded(socket.socket.connect)
    socket.socket.connect_ex = guarded(socket.socket.connect_ex)
    import pytest
    mode = "full" if args.full else "focused"
    options = ["-q", "--tb=short", "--junitxml=" + str(output / (mode + ".xml")),
               "--basetemp=" + str(output / (mode + "-temp"))]
    if not args.full:
        options += ["tests/test_controlled_live.py", "tests/test_controlled_live_postgresql.py",
                    "tests/test_production_graph_worker.py", "tests/test_graph_model_adapter.py",
                    "tests/test_graph_postgresql.py", "tests/test_case_mentor.py",
                    "tests/test_case_mentor_postgresql.py", "tests/test_case_mentor_dialogue_postgresql.py",
                    "tests/test_copilot_api.py", "tests/test_copilot_sync_replay_postgresql.py",
                    "tests/test_provider_request_telemetry.py"]
    return pytest.main(options)


if __name__ == "__main__":
    raise SystemExit(main())
