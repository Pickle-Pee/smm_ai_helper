"""CI-only real entrypoint, Redis outage/recovery and SIGTERM smoke probe."""
import json
import os
import subprocess
import time


def compose(*args):
    return subprocess.check_output(["docker", "compose", *args], text=True).strip()


def inspect_worker():
    container = compose("ps", "--all", "-q", "worker")
    assert container, "Worker container missing"
    return json.loads(subprocess.check_output(["docker", "inspect", container], text=True))[0]


def assert_running():
    state = inspect_worker()
    assert state["State"]["Running"] and state["RestartCount"] == 0, "Worker stopped or restarted"
    logs = compose("logs", "--no-color", "--since", state["State"]["StartedAt"], "worker")
    assert "Worker lanes ready fixed=2 graph=1 registry=1.2.0" in logs
    assert "Traceback" not in logs


def wait_ready():
    deadline = time.monotonic() + 30
    while True:
        try:
            assert_running()
            return
        except AssertionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(.5)


def main():
    if os.environ.get("CI") != "true" or not os.environ.get("COMPOSE_PROJECT_NAME", "").startswith("smm-mvp-ci-"):
        raise SystemExit("Requires a disposable smm-mvp-ci-* CI Compose project")
    wait_ready()
    try:
        compose("stop", "redis")
        time.sleep(4)  # Both lanes repeatedly encounter unavailable Redis.
        assert_running()
    finally:
        compose("start", "redis")
    time.sleep(3)
    assert_running()
    compose("stop", "--timeout", "10", "worker")
    state = inspect_worker()["State"]
    assert state["ExitCode"] == 0 and not state["OOMKilled"], "Worker did not handle SIGTERM cleanly"
    compose("start", "worker")
    wait_ready()
    print("Worker smoke passed: fixed=2 + graph=1, Registry 1.2.0, Redis loss/recovery, clean SIGTERM/restart; providers disabled.")


if __name__ == "__main__":
    main()
