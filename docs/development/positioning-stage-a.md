# POSITIONING Stage A: diagnostic-only change

Base: `0441c49e3938c962f5165adae4f96916df164e1a`, equal to fetched
`origin/master` on 2026-10-18. Branch: `codex/positioning-contract`.

Execution path: graph worker -> GraphExecutionService.load_work -> dispatcher ->
PositioningExecutor.execute -> BaseExecutor.generate -> exact JSON Schema ->
Pydantic -> build_result -> validate_statement. The graph service sets
`ModuleExecutionRequest.execution_id = item.job_id`; join this identifier with
existing worker job/run events. Standalone executions retain their execution ID;
no synthetic job identity is inferred.

StatementSemanticsError now retains an internal location/category snapshot at the
statement loop. The INFO diagnostic includes output_index, registry-approved
output_name, closed kind, cited local evidence categories, semantic rule,
execution_id, schema_version and validation/provider schema SHA256, using the
existing schema_measurement canonicalization. Unknown evidence labels become
`other`. Empty local support yields an empty category list. No claim text,
evidence IDs/values, source, objective, instruction, response, credentials or
arbitrary label enters this event. Existing warning formats and externally
sanitized errors stay unchanged. All outcomes, retries, wire schemas, budgets,
payload versions and persisted artifacts are unchanged.

Tests: new `test_positioning_statement_metadata.py` covers positions 0, 1, 2, 3,
permuted outputs, known and unknown categories, internal exception retention,
fingerprint/execution correlation and private sentinels. Original replay,
terminal-job, network guard, projection and privacy tests are retained.

Rollout after independent approval: ship A alone, retain normal INFO telemetry,
correlate one future rejection with worker job/run events, verify closed metadata.
Rollback: revert A; no schema/data migration or historical job mutation. A does
not resolve the grounding schema gap and does not authorize re-execution.

Validation and review results are recorded in `positioning-contract-review.md`.

Final Stage A regression: 659 passed, 4 warnings in 43.54s. Command: root .venv python -m pytest -q tests/test_positioning_statement_metadata.py tests/test_positioning_diagnostics.py tests/test_positioning_output.py tests/test_positioning_seed_contract.py tests/test_statement_support_contract.py tests/test_support_identity_schema.py tests/test_module_executors.py tests/test_positioning_schema_diagnostics.py tests/test_positioning_provider_projection.py tests/test_positioning_equivalent_schema.py --basetemp=.pytest-stage-a --disable-warnings --tb=short. Independent static review: no unresolved material findings. Initial runs exposed fixture issues and Windows sandbox/system-temp limitations; final run used workspace temp and unsandboxed local socketpair.
