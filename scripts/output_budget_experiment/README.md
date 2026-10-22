# Isolated POSITIONING budget campaign

This is operational diagnostic tooling, never a production entrypoint. The
retained campaign already consumed 128K and is terminal. Do not rerun it or delete
its receipts/markers. A new campaign requires explicit new identities, namespace,
directory/container/network names and a separate spending decision.

The completed campaign lives at
`/opt/smm_ai_helper_e2e/output-budget-experiment`. It retains the exact
`frozen-request.json`, `saved-plan.json`, original reconstruction, archived source,
private raw provider envelope and safe evidence. Never copy `private-live.env` or
the older `secrets/staging.env` into Git or an evidence bundle.

For initial preparation in a newly reviewed campaign, make `source.tar` with
`git archive <exact-sha>`, supply the two retained synthetic fixture files, and
copy operational scripts from this directory to the campaign root. Run
`python3 setup_server.py <exact-sha>` once. It refuses existing network/container
names rather than clearing their data. `server_container.py migrate` upgrades
the independent campaign DB; `test` uses the separate disposable test DB and an
internal network with fake credentials.

`server_container.py verify` runs the real original executor without HTTP,
records byte/value comparisons and, only on value equality, freezes its JSON key
ordering. `preflight_server.py` does non-generating model lookup and equivalent
Responses input token counting. The current key is read privately on the server;
no key is passed in argv.

Each numeric mode of `server_container.py` is **a paid action**, separately
selected by the operator after reviewing gates. There is no loop. It enforces
progression, but the operator must additionally honor the experiment stop rules.
The real runner asserts every outbound payload equals the frozen request with
only its cap changed, commits admission, uses one real graph job/lease/worker and
validates through the original executor and Quality Gates. Its fixture-only
historical module ID preserves evidence IDs; durable job/run/lease/owner are new.

`inspect_response.py` only GETs the saved response. `server_container.py replay`
uses fake credentials and an internal network to check terminal-job durability.
`finish_server.py` snapshots the ledger, checks production/old evidence, stops
only the new DB and removes only the new temporary API-key env file. Its volume
is intentionally retained.

Regression command (fake credentials, explicitly disposable PostgreSQL):

```text
python -m pytest -q tests/test_positioning_budget_experiment.py tests/test_module_output_budget.py tests/test_controlled_live.py tests/test_controlled_live_postgresql.py tests/test_graph_model_adapter.py tests/test_production_graph_worker.py tests/test_provider_request_telemetry.py tests/test_positioning_output.py tests/test_positioning_seed_contract.py
```

See `docs/reviews/pr129-output-budget-experiment.md` for actual source identity,
authorization, results, costs, limitations and cleanup.
