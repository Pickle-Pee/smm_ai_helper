"""CI-only probe of real backend/worker containers and their shared media volume.

The CI job owns an isolated Compose project with fake credentials and providers
disabled. No polling bot is started. 'seed' creates an incomplete run (no Job)
and a test image; 'verify' runs after both app containers are recreated.
"""
import base64
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen

PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jA8sAAAAASUVORK5CYII="
EVIDENCE = Path(".local-test/container-evidence.json")


def docker(*args):
    return subprocess.check_output(["docker", "compose", *args], text=True).strip()


def request(path, *, payload=None, actor=123):
    body = json.dumps(payload).encode() if payload is not None else None
    req = Request("http://127.0.0.1:8000" + path, data=body, headers={
        "Authorization": "Bearer offline-container-secret", "X-Telegram-User-ID": str(actor),
        "Content-Type": "application/json",
    })
    with urlopen(req, timeout=10) as response:
        return response.read()


def owned_snapshot_probe(mode):
    """Run in separate backend processes, before and after container recreation."""
    source = '''
import asyncio, hashlib, json
from sqlalchemy import select
from app.db import AsyncSessionLocal
from app.models import User
from app.product_context.contracts import OwnedSiteRequest, Extraction, ConfirmedBusinessFact
from app.product_context.service import OwnedProductEvidenceService
from app.product_context.snapshot_store import OwnedSnapshotStore
from app.product_context.projection import project_confirmation

async def check():
    url = "https://owned.example/product"
    quote = "Appointment reminders are included."
    extraction = Extraction.model_validate_json(json.dumps({"statements": [{
        "field": "stated_features_capabilities", "kind": "OBSERVATION",
        "text": quote, "excerpts": [quote]}]}))
    expected = OwnedProductEvidenceService._snapshot(OwnedSiteRequest(owned_site_url=url),
        url, "", [quote], extraction)
    async with AsyncSessionLocal() as session:
        owner = await session.scalar(select(User.id).where(User.telegram_id == 123))
    assert owner is not None
    store = OwnedSnapshotStore(AsyncSessionLocal)
    if MODE == "seed":
        await store.save(owner, "container-owned-confirmation", expected)
    snapshot = await store.load(owner, "container-owned-confirmation", expected.snapshot_id, url)
    assert snapshot == expected
    truth = project_confirmation(snapshot, ConfirmedBusinessFact(snapshot_id=snapshot.snapshot_id,
        statement_ids=tuple(s.statement_id for s in snapshot.statements),
        confirmed_by=f"user:{owner}", confirmation_reference="container-explicit-confirmation"))
    assert truth.fact.value["trust"] == "confirmed_business_fact"
    print(hashlib.sha256(snapshot.model_dump_json().encode()).hexdigest())
asyncio.run(check())
'''
    return docker("exec", "-T", "backend", "python", "-c", "MODE = " + repr(mode) + "\n" + source)


def main():
    if os.environ.get("CI") != "true" or not os.environ.get("COMPOSE_PROJECT_NAME", "").startswith("smm-mvp-ci-"):
        raise SystemExit("This probe requires the dedicated disposable smm-mvp-ci-* CI project.")
    assert json.loads(request("/health")) == {"status": "ok"}
    schema = json.loads(request("/openapi.json"))
    assert {"/copilot/execute", "/copilot/runs/{run_id}"} <= set(schema["paths"])
    # Prove the new authenticated router is served, without invoking any provider.
    try:
        request("/copilot/execute", payload={"request_key": "smoke", "message": ""})
    except HTTPError as exc:
        assert exc.code == 422 and json.loads(exc.read())["code"] == "invalid_request"
    else:
        raise AssertionError("Copilot accepted an invalid request")
    if sys.argv[1] == "seed":
        result = json.loads(request("/workflows", payload={"request_key": "container-recovery", "competitor_url": "https://example.com"}))
        assert result["status"] == "needs_input" and result["jobs"] == []
        image_id = docker("exec", "-T", "worker", "python", "-c",
            "import base64; from app.services.image_orchestrator import ImageOrchestrator; "
            f"print(ImageOrchestrator()._save_image(base64.b64decode('{PNG}'), '123'))")
        assert re.fullmatch(r"[0-9a-f]{32}", image_id)
        evidence = {"run_id": result["run_id"], "image_id": image_id,
                    "owned_snapshot_digest": owned_snapshot_probe("seed"),
                    "backend_container": docker("ps", "-q", "backend"), "worker_container": docker("ps", "-q", "worker")}
        EVIDENCE.parent.mkdir(exist_ok=True)
        EVIDENCE.write_text(json.dumps(evidence))
    elif sys.argv[1] == "verify":
        evidence = json.loads(EVIDENCE.read_text())
        assert docker("ps", "-q", "backend") != evidence["backend_container"]
        assert docker("ps", "-q", "worker") != evidence["worker_container"]
        result = json.loads(request("/workflows/" + evidence["run_id"]))
        assert result["status"] == "needs_input" and result["jobs"] == []
        assert owned_snapshot_probe("verify") == evidence["owned_snapshot_digest"]
    else:
        raise SystemExit("Use seed or verify")
    path = "/images/" + evidence["image_id"] + ".png"
    assert request(path) == base64.b64decode(PNG)
    try:
        request(path, actor=124)
    except HTTPError as exc:
        assert exc.code == 404
    else:
        raise AssertionError("A foreign actor retrieved private media")
    print(f"Container persistence {sys.argv[1]} passed: durable run, owned confirmation snapshot, shared image bytes and owner checks.")


if __name__ == "__main__":
    main()
