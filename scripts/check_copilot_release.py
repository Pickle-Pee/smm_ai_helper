"""CI-only active graph recovery through real containers and OS SIGTERM.

Paid provider and Telegram transports are replaced in the CI overlay only.
Database state, API, graph composition, workers and bot polling lifecycle are real.
"""
import json
import os
import subprocess
import time
from urllib.error import HTTPError, URLError

from check_container_persistence import request


def compose(*args):
    return subprocess.check_output(["docker", "compose", "-f", "docker-compose.yaml", "-f", "tests/compose.release.yaml", *args], text=True).strip()


def inspect(service):
    cid = compose("ps", "--all", "-q", service)
    return json.loads(subprocess.check_output(["docker", "inspect", cid], text=True))[0]


def wait(check, *, timeout=60):
    end = time.monotonic() + timeout
    while True:
        try:
            result = check()
            if result:
                return result
        except (HTTPError, URLError, ConnectionError):
            pass
        if time.monotonic() >= end:
            raise AssertionError("Container release condition timed out")
        time.sleep(.25)


def provider(path="/state", payload=None):
    code = ("import json; from urllib.request import Request,urlopen; "
            f"r=Request('http://localhost:8090{path}',data={repr(json.dumps(payload).encode()) if payload is not None else 'None'},"
            "headers={'Content-Type':'application/json'}); print(urlopen(r,timeout=5).read().decode())")
    return json.loads(compose("exec", "-T", "fake-provider", "python", "-c", code))


def clean_stop(service):
    compose("stop", "--timeout", "10", service)
    state = inspect(service)["State"]
    assert state["ExitCode"] == 0 and not state["OOMKilled"], (service, state["ExitCode"])


def database_probe(rid, *, expire=False):
    # Explicitly disposable CI only. Advance the test lease clock instead of
    # waiting 330 seconds; never mutate statuses or use this in operator steps.
    code = '''import asyncio, json
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from app.db import AsyncSessionLocal
from app.models import Job, JobExecution, MarketingArtifact
async def main():
    async with AsyncSessionLocal() as s, s.begin():
        jobs = (await s.scalars(select(Job).where(Job.marketing_run_id == RID))).all()
        artifacts = (await s.scalars(select(MarketingArtifact).where(MarketingArtifact.run_id == RID))).all()
        leases = [await s.get(JobExecution, j.job_id) for j in jobs]
        if EXPIRE:
            for lease in leases:
                if lease.claim_token:
                    lease.lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        print(json.dumps({'statuses': [j.status.value for j in jobs], 'artifacts': len(artifacts),
                          'attempts': [l.attempts for l in leases], 'keys': [a.artifact_key for a in artifacts]}))
asyncio.run(main())
'''.replace("RID", repr(rid)).replace("EXPIRE", repr(expire))
    return json.loads(compose("exec", "-T", "backend", "python", "-c", code))


def main():
    if os.environ.get("CI") != "true" or not os.environ.get("COMPOSE_PROJECT_NAME", "").startswith("smm-mvp-ci-"):
        raise SystemExit("Requires an isolated smm-mvp-ci-* CI Compose project")
    compose("up", "--build", "--wait", "--wait-timeout", "120", "-d", "fake-provider", "backend", "worker", "bot")
    wait(lambda: "OFFLINE_TELEGRAM_POLL_READY" in compose("logs", "--no-color", "bot"))
    clean_stop("bot")
    compose("start", "bot")
    # Redis is unavailable before acceptance AND while the first node commits.
    compose("stop", "redis")
    context = dict(business_goal="Grow bookings", product="Scheduling software", target="Clinics",
        customer_job_or_need="Reduce delays", relevant_alternative="Spreadsheets", product_truth="Appointment reminders")
    started = json.loads(request("/copilot/execute", actor=456, payload={
        "request_key": "release-recovery", "message": "Build a strategy", "context": context}))
    assert started["kind"] == "WORKFLOW_STARTED"
    rid = started["run_id"]
    wait(lambda: provider()["waiting"] >= 1)
    before = database_probe(rid)
    assert before["artifacts"] == 1 and "running" in before["statuses"]
    old_backend, old_worker = inspect("backend")["Id"], inspect("worker")["Id"]
    clean_stop("worker")  # SIGTERM during provider call: keep active lease, no FAILED.
    assert database_probe(rid)["statuses"] == before["statuses"]
    clean_stop("backend")
    compose("up", "--no-build", "--no-deps", "--force-recreate", "--wait", "--wait-timeout", "60", "-d", "backend")
    assert inspect("backend")["Id"] != old_backend
    assert rid in [v["run_id"] for v in json.loads(request("/copilot/runs", actor=456))["items"]]
    assert json.loads(request(started["status_url"], actor=456))["strategy"] is None
    database_probe(rid, expire=True)
    provider("/release", {})
    compose("up", "--no-build", "--no-deps", "--force-recreate", "-d", "worker")
    assert inspect("worker")["Id"] != old_worker
    final = wait(lambda: (v if (v := json.loads(request(started["status_url"], actor=456)))["status"] == "COMPLETED" else None))
    assert final["strategy"] and final["experiments"]
    saved = database_probe(rid)
    assert saved["statuses"] == ["succeeded"] * 3 and saved["artifacts"] == len(set(saved["keys"])) == 3
    assert sorted(saved["attempts"]) == [1, 1, 2]
    assert provider()["module_calls"] == 4  # At-least-once external execution, exactly one accepted artifact/node.
    compose("start", "redis")
    wait(lambda: json.loads(request("/ready"))["status"] == "ready")
    clean_stop("worker")  # Also cover idle SIGTERM.
    clean_stop("bot")
    compose("start", "worker")
    print("Copilot release containers PASS: accepted graph + first artifact, Redis outage, active/idle worker SIGTERM, "
          "backend SIGTERM/recreation, bot SIGTERM/restart, lease replacement, 3 accepted artifacts and recovered presentation.")


if __name__ == "__main__":
    main()
