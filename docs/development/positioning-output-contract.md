# POSITIONING output contract — issue #77

## Diagnosis

Base: `e0ad7cdc444cbcae691ce8ed5e48a79403e8c495`, the merge of PR #80 into
master. No OpenSpec or persistence changes are required.

Two controlled calls through the real `production_model_call` and original
executor reproduced `ExecutorOutputError` with the cause
`Differentiation requires hypothesis marking in v1`. The local configured model
was `gpt-6-sol`; inputs were the synthetic photography-course context already
used in Copilot tests. Only allowlisted diagnostic categories were printed;
neither raw responses nor credentials were saved.

The second call established all of the following:

- Strict JSON and `PositioningOutput` validation succeeded.
- All 16 requested output names matched exactly, including `validation_plan.`.
- The four product-claim outputs cited supplied product truth/proof.
- `differentiation` and `points_of_difference` were `HYPOTHESIS`.
- `USP_directions` was `RECOMMENDATION`.
- `PositioningExecutor.validate_statement()` rejected that last classification.

The precise original failure stage is **statement_semantics_invalid**. The wire
schema permitted four kinds for every output, although the server requires
HYPOTHESIS for all three differentiation outputs. The old fake always chose
HYPOTHESIS and cited every evidence ID, concealing this production mismatch.
This is a live local reproduction of the reported failure class, not a claim
to have recovered the historical production response.

## Implementation and compatibility

`PositioningOutput.outputs.items` now uses a nested `anyOf` with disjoint output
names. The differentiation variant requires `kind = HYPOTHESIS`; the remaining
outputs retain their four permitted kinds. This avoids a root union or
provider-specific schema patch, and preserves the existing list representation,
payload version, registry names and public DTOs. A provider obeying the supplied
strict schema cannot emit the observed invalid pair. A nonconforming provider
still fails closed, now at **schema_invalid**.

The instruction names the three exact outputs and explicitly requires local
`product_truth`/`existing_proof` evidence for RTB, value_proposition,
positioning_statement and offer. The original semantic validators remain in
place. Required inputs still block before generation; parent-only product
support, unknown references, duplicate support, unsupported statements and
incorrect output coverage are not accepted. Coverage also rejects repeated
output names instead of counting them as extra claims.

Shared internal diagnostics expose `ExecutorOutputError.stage` as a closed enum:
`json_invalid`, `schema_invalid`, `output_coverage_invalid`,
`support_identity_invalid`, `evidence_reference_invalid`,
`parent_reference_invalid`, `support_missing`, `statement_semantics_invalid`,
`result_contract_invalid`. The executor emits only module and stage; chained
validation tracebacks are suppressed because they can contain model text. No raw
response, prompt, context value, evidence payload or API key is logged.

Provider exceptions propagate unchanged. Executor errors remain non-transient.
The single attempt and bounded 4000-token adapter budget are unchanged. Quality
Gates, full-claim acceptance, confidence caps, lineage, graph transactions and
public HTTP error mapping are unchanged. Issue #78 remains separate.

## Verification

`tests/positioning_provider.py` is a synthetic HTTP provider double with varied
kinds and selective evidence. It proposes RECOMMENDATION for USP_directions
when the wire schema permits it and must select HYPOTHESIS under the fixed
schema. It contains no captured live output. Regressions verify the minimal
counterexample, provider wire schema, exact registry/planner coverage, all
product-support slots, safe stages, invalid support, direct Copilot (typed and
natural-language projection), and worker Quality Gates/downstream readiness.
The PostgreSQL regression additionally checks persisted acceptance and a pending
virtual_cmo job; it requires `MVP_TEST_DATABASE_URL` pointing to a disposable
database whose name contains `smm_mvp_test`.

A controlled live call after the fix returned PASS_WITH_LIMITATIONS, 16 outputs
and HYPOTHESIS for all three differentiation outputs. This confirms acceptance
of the new schema by the locally configured provider; it is not a guarantee
that arbitrary model output will pass every other semantic validation.

Local checks executed with `.venv/Scripts/python.exe`:

- `-m pytest tests/test_positioning_output.py tests/test_module_executors.py tests/test_graph_model_adapter.py -q`: 166 passed.
- `-m pytest -q`: 1519 passed, 160 skipped (PostgreSQL/Redis integration infrastructure not configured).
- `-m pytest tests/test_strategy_builder_postgresql.py -q`: 34 skipped; Docker daemon unavailable locally.
- `-m compileall app bot` and `git diff --check`: passed.

No migrations were added. The durable PostgreSQL regression must run in CI or
an environment with the disposable database configured; the local worker/gate
regression verifies acceptance and dependency readiness without persistence.

## Production E2E

After deploying the reviewed change to both backend and worker, run from the
server's Compose directory. Set `POSITIONING_E2E_ACTOR_ID` to your test Telegram
actor ID. The command uses the container's existing backend credential and
sends only synthetic context. It performs one direct request with a fresh key
and prints only status/kind/count, not findings or credentials.

```bash
export POSITIONING_E2E_ACTOR_ID=123456789
docker compose exec -T -e POSITIONING_E2E_ACTOR_ID="$POSITIONING_E2E_ACTOR_ID" backend python - <<'PY'
import os
import uuid
import httpx
from app.config import settings

payload = {
    "request_key": "positioning-77-" + uuid.uuid4().hex,
    "message": "Помоги сформулировать позиционирование онлайн-курса фотографии для начинающих.",
    "context": {
        "product": "онлайн-курса фотографии",
        "target": "люди, которые только купили камеру или снимают на телефон и хотят перестать фотографировать наугад",
        "customer_job_or_need": "понять основы композиции, света и настроек и начать получать предсказуемо хорошие кадры",
        "relevant_alternative": "бесплатные ролики на YouTube и разрозненные статьи",
        "product_truth": "Наш курс последовательно объясняет базу и даёт практические задания с обратной связью.",
    },
}
headers = {
    "Authorization": "Bearer " + settings.BOT_BACKEND_TOKEN,
    "X-Telegram-User-Id": str(int(os.environ["POSITIONING_E2E_ACTOR_ID"])),
}
with httpx.Client(base_url="http://127.0.0.1:8000", timeout=330) as client:
    response = client.post("/copilot/execute", headers=headers, json=payload)
data = response.json()
kind = data.get("kind")
count = len(data.get("result", {}).get("findings", []))
print({"http_status": response.status_code, "kind": kind, "findings_count": count})
assert response.status_code == 200 and kind == "MODULE_RESULT" and count == 16
PY
```

If the request fails, inspect backend logs for `Module output rejected
module=POSITIONING stage=...`; do not enable model/prompt body logging. The public
503 classification intentionally stays unchanged in this PR. For Strategy
Builder, repeat with a fresh request key, a strategy request and `business_goal`,
then inspect the owner-scoped run status: the first POSITIONING artifact must be
accepted and virtual_cmo becomes eligible. Later module failures are independent
of this fix.
