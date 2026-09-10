"""Offline-provider smoke using an explicitly disposable, real PostgreSQL DB.

Run from the repository root with MVP_TEST_DATABASE_URL configured. The suite
uses no real OpenAI or Telegram calls. It includes an abruptly stopped worker
subprocess and its replacement, HTTP ownership, result persistence and delivery.
"""
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit


def main():
    database = os.environ.get("MVP_TEST_DATABASE_URL", "")
    if "smm_mvp_test" not in urlsplit(database).path:
        raise SystemExit("Set MVP_TEST_DATABASE_URL to an explicitly disposable PostgreSQL database containing smm_mvp_test in its name.")
    env = {**os.environ, "DATABASE_URL": database, "OPENAI_API_KEY": "offline-test-key",
           "TELEGRAM_BOT_TOKEN": "123456:offline-test-token", "BOT_BACKEND_TOKEN": "offline-test-secret"}
    return subprocess.call([sys.executable, "-m", "pytest", "-q", "--tb=short",
                            "tests/test_marketing_mvp_postgresql.py", "tests/test_workflow_provider_protocols.py"],
                           cwd=Path(__file__).resolve().parents[1], env=env)


if __name__ == "__main__":
    raise SystemExit(main())
