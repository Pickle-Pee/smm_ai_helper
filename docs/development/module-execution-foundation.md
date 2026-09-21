# Module execution foundation

The internal `app/module_execution/` foundation now has three explicitly composed implementations in `executors/`, described in [first module executors](first-module-executors.md). Registry `1.0.0` remains the metadata-only default; executable Registry `1.1.0` must be requested explicitly. There are no current ingress/worker consumers. The fixed competitor -> creative -> opt-in mentor workflow continues through `app/workflows/executors.py` and its explicit quality adapter. The generic Orchestrator remains `PLANNING_ONLY`.

## Contract and ownership

`MODULE_EXECUTION_CONTRACT_VERSION = "module_executor.v1"` is the only version the dispatcher executes. Contracts are frozen, slotted, keyword-only dataclasses. They reject unknown fields and coercive types; callers supply canonical `ModuleId` enum values, never aliases or enum strings.

| Contract | Fields |
| --- | --- |
| `ModuleExecutionRequest` | `execution_id: str`, `module_id: ModuleId`, `objective: str`, `expected_outputs: tuple[str, ...]`, `context_packet: ContextPacket`, `upstream_results: tuple[UpstreamExecutionResult, ...] = ()` |
| `ModuleExecutionResult` | `module_id: ModuleId`, `schema_version: str`, `payload: Mapping[str, ImmutableJsonValue]`, `normalized_result: NormalizedModuleResult` |
| `UpstreamExecutionResult` | `producer_node_id: str`, `result: ModuleExecutionResult`; derived `module_id` and `result_id` properties |
| Declarative `ExecutionBinding` | `executor_key: str`, `contract_version: str`, `compatibility: Literal["exact"]`, `evidence: str` |

`execution_id`, `producer_node_id` and payload `schema_version` are 1–128 character lowercase identifiers matching `[a-z0-9][a-z0-9._:-]{0,127}`. They are opaque caller-supplied identities, not database ownership, claims or deduplication tokens. Expected outputs must be a non-empty list/tuple of unique non-blank exact strings, copied into a tuple. The existing `ContextPacket` carries scoped context without duplicated brand/fact/tool fields. Its caller owns authorization and scoping; the dispatcher does not fetch or expand context.

Payload input must be an exact built-in JSON object (`dict`). The existing Orchestrator freezer recursively copies string-keyed dictionaries to read-only mapping proxies and lists/tuples to tuples, retaining exact `None`, `bool`, `int`, finite `float` and `str` scalars. Custom containers/scalar subclasses, arbitrary runtime objects, sets, bytes, non-finite numbers, non-string keys and cycles fail closed. Mapping proxies are output-only, consistent with the existing context contract. Pass the complete immutable result into an upstream envelope instead of reconstructing it from its frozen payload. Typed context and normalized quality values are reused as immutable values constructed through their existing contracts.

Every execution result requires `normalized_result.module_id is module_id`. The upstream envelope composes the same result rather than copying its module/payload/quality fields, so these cannot disagree. Its result identity is `result.normalized_result.result_id` with the existing `res_...` rules. Result identities must be unique across one request, including when producer node IDs differ. Distinct results from the same producer are allowed; no new node lifecycle policy is implied.

`schema_version` describes the module-specific payload, separately from the executor protocol version. The foundation checks JSON/envelope structure; future implementations own their exact payload schemas and the relationship between payload and normalized claims. A `NormalizedModuleResult` supplies provenance/quality representation, not proof that an evaluator already accepted the result. The dispatcher never invokes an evaluator or introduces quality semantics. There is no hidden reasoning field, duplicate claims/evidence format, resource lifecycle, provider configuration or application service in the request/result envelope. Dedicated asset-reference fields are deferred until a concrete CREATOR implementation establishes their requirements; no local-file or Telegram URL contract is introduced here.

## Registry, dispatcher and dependencies

```text
Declarative data flow (future caller supplies the binding):
ModuleId -> ModuleRegistry descriptor -> ExecutionBinding data
         -> ModuleExecutorRegistry exact lookup -> ModuleExecutorDispatcher -> ModuleExecutor

Python dependencies:
module_execution -> module_registry (declarative types)
module_execution -> marketing_orchestrator.contracts (ContextPacket / JSON freezer)
module_execution -> marketing_orchestrator.quality_gates.contracts (NormalizedModuleResult)
marketing_orchestrator / quality_gates -> module_registry

No reverse dependency into module_execution; no ModuleRegistry -> AgentRegistry -> AgentRunner path.
```

`ModuleExecutor` is a protocol with read-only `executor_key`, `module_id`, `contract_version` metadata and `async execute(request) -> ModuleExecutionResult`. One implementation targets exactly one module. Dependencies are supplied to implementations explicitly; the protocol has no execution wrapper or provider default.

Construct `ModuleExecutorRegistry(executors)` explicitly. The default is empty. It snapshots registrations and their metadata, rejects duplicate keys/invalid metadata/non-async operations, and resolves only the exact key without invoking the executor. Metadata changes after registration fail closed. Keys are 1–128 characters matching `[a-z][a-z0-9]*(?:[._:-][a-z0-9]+)*`; lookup performs no trimming, case folding, alias resolution or dynamic imports. There are no decorators, mutable global registrations or service locators.

Construct `ModuleExecutorDispatcher(registry)` and call `await dispatcher.dispatch(binding, request)`. It checks typed envelopes, exact compatibility, availability, both versions against `module_executor.v1`, and request/executor module identity before invoking once. It then requires a `ModuleExecutionResult` with matching module and normalized-result identity. Unknown executors, invalid metadata, version mismatches and module mismatches have separate boundary errors. Executor/provider exceptions and cancellation propagate unchanged; there is no retry, categorization, transaction, Job, Redis wakeup or delivery logic.

The binding declares a syntactically valid version, while the dispatcher owns supported-version checks. This keeps product metadata independent of installed runtimes. The former `agent_id` shape is intentionally removed; this changes no persisted `1.0.0` resource, because it has no bindings. Registry `1.0.0` loading and direct construction still reject any binding. Explicit `1.1.0` validates exactly its three approved bindings; the executor factory additionally validates implementation inventory, keys, module IDs and contract versions. `executor_keys` exposes an immutable inventory for that check.

## Compatibility and next step

All 15 Registry `1.0.0` descriptors remain `metadata_only` with `execution_binding = null`. The tracked `v1.0.0.json` resource is unchanged relative to the merged base. Normalization is UTF-8 `json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":"))`; the SHA-256 remains:

`25261485245902066cb6c59ef6cc612b18ab4cdabeebff6768e49816ba716918`

`AgentRegistry`, `AgentRunner`, `TaskPipelineService`, fixed `MarketingExecutors`, `MarketingWorkflowService`, Quality Gates evaluation, the planner, Copilot `ExecutionPolicy`, public DTOs, API/Telegram ingress, workers, persistence, Redis and delivery retain their behavior. No migrations or database schema changes are included. The first implementations and separately versioned executable Registry are now available internally. Next is PlanCompiler / generic graph execution integration; generic plan execution is not implemented here.

## Foundation-stage verification (PR #56)

`tests/test_module_execution.py` covers deep freezing, strict inputs, upstream identity/coherence, key and metadata stability, explicit registration, exact dispatch, single invocation, unchanged exception/cancellation propagation, no repeated quality evaluation, legacy AgentRunner behavior, no production consumers and all 24 fresh import orders for the four boundaries. Existing Registry tests retain the normalized checksum guard and reject both mapping-loaded and directly constructed bindings without consulting legacy agents.

Required commands run using the repository `.venv` (system Python has no pytest):

```text
python -m pytest tests/test_module_execution.py tests/test_module_registry.py tests/test_marketing_orchestrator.py tests/test_marketing_copilot.py
python -m pytest
python -m compileall app bot
git diff --check
```

Local results: focused suite **394 passed**; full suite **944 passed, 1 skipped** (real Redis integration is not configured); compile and whitespace checks passed. PostgreSQL integration tests ran using separately created disposable `durable_job_test_module_execution` and `smm_mvp_test_module_execution` databases on the local test server; no application database was used. Existing deprecation warnings remain. The Registry checksum was calculated for both `origin/sale-ready` and the working tree and matched the value above.

The full run initially exposed the existing Quality Gates import guard. That guard now permits exactly the execution contract's `NormalizedModuleResult` import in addition to the fixed workflow adapter; it still forbids other consumers. Final code review checked single-call dispatch, exception propagation, dependency direction, absence of production integration and the unchanged Registry resource/legacy runtime paths.
