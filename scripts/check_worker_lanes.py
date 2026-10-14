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
    assert "Worker lanes ready fixed=2 graph=1 registry=1.3.0" in logs
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


def control(action, *args):
    # Disposable CI only (main guard below). Never export the DSN or use this
    # application-role shortcut in the protected production operator procedure.
    code = ("import os,sys; from app.worker_control import main; "
            "os.environ['WORKER_DRAIN_DATABASE_URL']=os.environ['DATABASE_URL']; "
            "sys.exit(main(sys.argv[1:]))")
    return json.loads(compose("exec", "-T", "worker", "python", "-c", code, action, *args))


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
    paused = control("pause")
    epoch = str(paused["epoch"])
    assert control("status", "--require-drained", "--expect-epoch", epoch)["drained"]
    compose("stop", "--timeout", "10", "worker")
    state = inspect_worker()["State"]
    assert state["ExitCode"] == 0 and not state["OOMKilled"], "Worker did not handle SIGTERM cleanly"
    compose("start", "worker")
    wait_ready()
    assert control("status", "--require-drained", "--expect-epoch", epoch)["admission"] == "paused"
    assert control("resume", "--expect-epoch", epoch)["admission"] == "open"
    print("Worker smoke passed: both lanes, Redis recovery, live drain gate, OS SIGTERM, persisted pause on restart; providers disabled.")


if __name__ == "__main__":
    main()
