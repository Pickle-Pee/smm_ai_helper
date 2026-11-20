# VIRTUAL_CMO incident: 30 October 2026

## Root cause and evidence

Run `8d2b8c87b934897e077efb0789983b97cfce947fe524e94859749a36d7f1407a`, job `d91601c5b4ff01456db646d3d5fccac0` failed after three empty, zero-usage incomplete Responses envelopes. Read-only production recovery found the accepted POSITIONING artifact, immutable plan and failed job. Current production builders reproduced instructions **53839 bytes**, input **41584 bytes**, schema **9700 bytes**, fingerprint `9c7f3d48d89d76394ae717c77bb18443a83e144a8639dbc711611f1937a37477`.

This is a reconstruction from current builders and the accepted graph, not an original outbound HTTP body capture. The schema fingerprint and all recorded sizes match; no historical instruction/input hashes were logged. Current image revision was `76b6c1b5a69877cd6029397e4e13db36070ad039`, effective model `gpt-5-mini`, effort `low`, output budget `16000`, HTTP timeout 60 s; configured API hostname `api.openai.com`, path `/v1`.

Two explicit baseline/candidate pairs isolate the outbound schema as a reproducible trigger. Baseline payload hash `33f131b0882e5b0f0c0c579c1c7e1200d7c266dab8d9eb1804473d2d3f5fd4e9` fails with empty `incomplete/max_output_tokens`. Removing only two mathematically redundant complete-object support ORs produces schema **4890 bytes**, fingerprint `0924d6708159f45780c3761f0460e0d817a6e1ddcbd8442679f39c4c6cea4328`; both candidate calls completed and passed the original local schema, Pydantic, numerical/provenance checks and Quality Gates. Instructions, input, model, effort and output budget were identical. Baseline repeated after the first candidate still failed. This establishes an application-side schema-shape trigger and an effective equivalent rewrite; it does not expose or prove the provider's internal failure mechanism.

Other factors tested separately: reduced/minimal Expert Core, accepted-claims/compact upstream, medium effort, doubled output budget, alternate instructions field, removed annotations/array bounds/numeric structure. See the complete ledger, including failures and a gpt-5 timeout. The synthetic gpt-5 sample passed; the incident gpt-5 sample timed out with unknown outcome. No production model substitution was made.

## Regression history

Historical Git sources were isolated in in-memory modules with identical synthetic support IDs (six evidence and sixteen parents, each 52 characters). These are historical schema reconstructions using current installed dependencies, not full historical system deployments.

| Revision | Instructions bytes | Schema bytes | Structural / resolved anyOf | Redundant support ORs |
|---|---:|---:|---|---:|
| Before #106, `5421c99` | 52921 | 5001 | 1 / 1 | 0 |
| #106, `8e11a43` | 52921 | 7580 | 3 / 3 | 2 |
| #107, `7f5b7cc` | 53839 | 9700 | 4 / 9 | 2 |
| #108, `681524a` | 53839 | unchanged | unchanged | 2 |
| #118, `1a0ab10` | 53839 | unchanged | unchanged | 2 |
| #119, `9ff8825` | 53839 | unchanged | unchanged | 2 |
| #120, `cd980fa` / current baseline | 53839 | 9700 | 4 / 9 | 2 |

The redundant ORs first appeared in #106 implementation `514deb8`: `support_response_schema` applies `parent_claim_ids.minItems=1` to the parent and branch objects. #107 implementation `07bdc3d` added numeric_context and its support union, duplicated into the complete-object branches, plus 918 instruction bytes. Expert Core remains 49876 bytes throughout. #108 increased the output budget; #118's catalog is off in this incident; #119 normalization and #120 observation occur only after model output and cannot cause the initial zero-output failure.

The three explicitly authorized historical-schema live tests all returned the same empty incomplete envelope, including the pre-#106 5001-byte schema. Therefore #106/#107 cannot be named the first failing change. Historical code traces the combination further back: `3d7051e` introduced statement support ORs; `3e87d79` introduced request-scoped support enum references on 7 October. Removing support enums alone from the current schema yielded accepted output, while dropping numeric structure alone did not. This identifies a reproducible interaction, not a proven first historical failing production commit. Current instructions/context were deliberately frozen in the historical-schema tests; full old runtime success was not established.

## Execution, ownership and retry

Telegram handler -> authenticated Copilot -> compiled plan -> PostgreSQL jobs -> GraphExecutionService.load_work -> dispatcher -> VirtualCMOExecutor -> BaseExecutor.generate -> production_model_call -> single-attempt Responses POST -> original local validation -> semantics -> Quality Gates -> fenced atomic artifact/job/run completion.

PostgreSQL owns durable state; Redis is a wakeup hint. The complete accepted upstream is preserved for lineage and gates. Its raw payload and normalized claims duplicate content in LLM input; compaction alone did not fix the incident and is not introduced in the production patch.

`RESPONSES_WORKFLOW_GOVERNANCE_ENABLED=false` and run.input_json containing only history_title explain `legacy_retry`. Governance implementation exists but is opt-in, records policy only on new runs, and does not migrate old runs when enabled later. Each original graph attempt owned one POST; logs show matching schema and payload sizes across all three attempts. No evidence of context loss or graph corruption was found in the restored accepted graph. Retry is not the fix and was not used to mask failed experiments.

## Fix and compatibility

`collapse_redundant_support_anyof` accepts an exact JSON-sensitive witness for `P AND (P OR Q) = P`, ignoring only the object's title annotation. It preserves every parent constraint, enum, reference and support floor. Ordinary evidence-or-parent ORs without a witness stay intact. Scope/evaluation-dependent keywords and non-direct/dangling references are refused. The original schema is copied, and BaseExecutor keeps its original local schema/Pydantic/semantic pipeline. Only CMO's provider-schema hook applies the rewrite.

No persisted schema, migration, DTO, registry, graph lifecycle, support identity, numerical acceptance or Quality Gate changes. Existing artifacts remain readable. Application rollback uses the previous immutable image with the same database.

`tools.virtual_cmo_ablation` provides an unprojected control, one-factor variants and offline measurements; live mode requires an exact expected payload hash and explicit opt-in, emits an authorization event before dispatch and permits one POST only. Raw data is not emitted. Relaxed schemas remain diagnostic and do not replace the original acceptance contract.

## Validation and acceptance status

Initial focused suite: 170 passed. Independent equivalent-schema review: 49 passed. Additional runner/projection tests initially: 34 passed. Initial full local suite with separate PostgreSQL 15 and Redis: 4565 passed, 10 failed; all failures were obsolete expectations of the former provider schema or inherited hook, while acceptance checks remained intact. Updated expectations retain all semantic/support rejection assertions. Final targeted/CI results must be recorded before production rollout.

Final targeted suite after expectation updates and review fixes: **229 passed**. Independent review found and resolved two diagnostic issues: retain closed-enum envelope failure reasons, and count a POST only at dispatch rather than before client construction. Tests cover both fixes and verify that provider mutation cannot weaken original local validation.

`compileall app bot`, disposable `alembic upgrade head` through `20261026_0013` and `alembic check` passed; no new upgrade operations. Local Docker daemon was unavailable. Container-smoke must be verified in CI for the final head.

Live Telegram end-to-end, history/continuation, restart, /new isolation, final production revision and final two-business acceptance are pending. A successful isolated CMO replay is not a completed Telegram strategy workflow.

## Evidence and limitations

[All live experiments](live-experiments.md), [structured metadata](experiments.json). Private originals/responses remain solely on the authorized server. No provider billing total was available; reported zero token usage is not called zero cost. No raw business data or secrets are published in this report.

Provider-internal grammar compilation details are not observable from our response envelopes. The historical live comparison did not establish a first failing commit: every tested historical schema failed on the frozen current input. Historical sources/dependencies and the full old runtime are distinct evidence classes. Failed attempts and unmet acceptance gates remain explicit.
