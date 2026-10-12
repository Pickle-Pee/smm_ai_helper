# VIRTUAL_CMO numeric-context audit and read-only replay

The historical incident is run `3a8ae9035bb622ad9eb55a7b10d3e610991c829a1578ba02c6ff7030c855f0f8`, job `6c350338c84ffc5dbe212ae201906bc6`. The recorded failure was `execution_invalid`, stage `statement_semantics_invalid`, rule `numerical_support_required`, field `numeric_context`. Without the original output, its concrete violation cannot be determined. The new closed reason codes do not establish the historical cause retroactively.

## Authoritative validation order

`VirtualCMOExecutor.execute` checks compatibility and required business goal/product context, scopes local first-party evidence and accepted parent claims, and calls the production model adapter once. The adapter retains the production model, VIRTUAL_CMO output budget, strict response schema and single-attempt transport policy.

The executor parses JSON with duplicate-key/non-finite-number rejection, checks the request-bound JSON Schema, and validates Pydantic `StrategyOutput`. VIRTUAL_CMO adds its economics limitation. IntelligenceExecutor rechecks post-mutation Pydantic bounds and rejects duplicate output names; BaseExecutor checks output coverage and constructs bounded assumptions/limitations. For each statement it rejects duplicate support identities, unresolved evidence/parent references and missing support before invoking statement semantics.

Numeric semantics reject digits in qualitative text/items. Each numeric_context item must cite its support in that statement, resolve to scoped evidence or accepted parents, and quote a complete eligible source unit. `context_units()` and `parent_context_units()` own extraction; units must contain digits plus alphabetic context. Structured parent claims expose validated summary/items/prior numeric quotes rather than serialized JSON or technical IDs. The complete quote must match exactly; substrings and changed values/units fail. Site assertions retain site attribution and parent numeric context does not gain authority. Strategy kind, required parent support and main_growth_constraint invariants follow; confidence is clamped, normalized claims are built, structured StrategyClaim values retain attribution. The independent QualityGateEvaluator still decides acceptance across the complete accepted ancestor closure.

Numeric-context errors preserve the nontransient stage/rule/location. Closed reasons describe the actual first failed numeric condition: `support_not_cited`, `support_not_found`, `source_has_no_eligible_quote`, `quote_is_fragment`, `quote_not_exact`, or `other_numeric_context_invalid`. Zero-based `output_index` and `numeric_context_index` identify positions only. Earlier schema/support failures keep their own stage and never receive a fabricated numeric reason. `ResultFailureRule` remains a separate validation stage.

## Isolated offline restoration

Run only as a standalone process, never import this tool into a worker. HTTP interception temporarily patches a process-local client factory. Do not run deployment, workers or queue dispatch. Do not change working environment flags.

Use a protected local snapshot named with schema version `virtual_cmo_diagnostic_snapshot.v1`. It contains `run`, active `plan_record`, `jobs`, and `artifacts` table projections in the same structure as `tools.positioning_diagnostics.restore_snapshot`. Obtain this projection through an approved read-only export; no exporter with write access is introduced here. Keep business values in the protected source file; never attach that file to a PR or log it.

```powershell
python -m tools.virtual_cmo_diagnostics --snapshot C:\Private\virtual-cmo-snapshot.json --run-id 3a8ae9035bb622ad9eb55a7b10d3e610991c829a1578ba02c6ff7030c855f0f8 --job-id 6c350338c84ffc5dbe212ae201906bc6
```

Alternatively `--database-read` replaces `--snapshot PATH`. Restoration reuses production graph validators inside `SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY`; it performs SELECTs without locking and never calls graph mutation/finish/advance, job writes, queues or capabilities. Offline snapshot restoration constructs no database session. Tests verify source immutability, read-only SQL preceding reads, source fingerprint/quality rejection and zero real network operations.

The compiled plan fingerprint, target routing, ancestor artifact fingerprints, accepted Quality Gates and dependency barrier are verified before provider access. The failed target is excluded from coverage to reconstruct its pre-dispatch request. The report emits only sizes, SHA-256 fingerprints, counts and fixed metadata labels, without request/response/source text, business numbers, support/claim/evidence IDs or exception strings.

Restoration uses current production builders and the current accepted graph. A fingerprint printed by this tool identifies that reconstruction; it cannot prove equality with a missing historical dispatch snapshot. Record the expected complete payload fingerprint independently from a trusted historical dispatch record if exact historical reproduction is required. If only a reviewed reconstruction is available, label it explicitly as a current reconstruction and obtain permission for that exact payload before any provider request. A hash copied unreviewed from a new reconstruction does not establish historical fidelity.

## Exactly one selected replay mode

`--mode baseline` is the default: the isolated executor disables the catalog regardless
of the deployment flag. This preserves the original request-building behavior. Historical
request equality still requires the independently recorded original full-payload hash;
current builders and accepted graph alone cannot establish it. Even an exact request
replay produces a new stochastic response, so it cannot identify the old violation.

`--mode catalog` enables the catalog only on this isolated executor instance. It adds the
existing bounded catalog and guidance to user input; it leaves schema, model, token policy,
server numeric rules and complete Quality Gates unchanged. Neither mode changes settings,
working environment flags, workers, persisted graph, jobs or database rows.

A CLI invocation accepts one mode only. Repeated `--mode` arguments are rejected even when
they repeat the same value. There is no automatic A/B sequence or retry. Capture records
the selected mode, and replay rejects a different mode before constructing an HTTP client.
The full payload SHA-256 is checked for the selected mode before a live client and again
against the rebuilt wire before POST. A baseline hash cannot authorize a catalog request.

## One provider request, only after separate authorization

No live call is authorized by the implementation task. The offline command above is sufficient for this delivery. A future operator must obtain separate permission for one provider call, record the authorized full payload SHA-256 from protected evidence, and then use:

```powershell
python -m tools.virtual_cmo_diagnostics --snapshot C:\Private\virtual-cmo-snapshot.json --run-id 3a8ae9035bb622ad9eb55a7b10d3e610991c829a1578ba02c6ff7030c855f0f8 --job-id 6c350338c84ffc5dbe212ae201906bc6 --expected-payload-sha256 APPROVED_SHA256 --authorize-one-provider-call
```

The command above defaults to baseline; `--mode baseline` can be stated explicitly.
The explicit one-call authorization switch and matching selected-mode full payload
fingerprint are mandatory. No alternative model, schema, output budget, fallback, repair
or automatic retry is available. A hard guard permits at most one POST across client
instances. Model, source or mode drift blocks HTTP. This is one isolated replay.

## Separately approved catalog verification

1. In a separate offline invocation, capture catalog-mode metadata and its complete payload
   hash without any provider call:

```powershell
python -m tools.virtual_cmo_diagnostics --snapshot C:\Private\virtual-cmo-snapshot.json --run-id 3a8ae9035bb622ad9eb55a7b10d3e610991c829a1578ba02c6ff7030c855f0f8 --job-id 6c350338c84ffc5dbe212ae201906bc6 --mode catalog
```

2. Have an authorized reviewer inspect the protected reconstructed inputs, source/graph
   fingerprints and catalog-mode request, and approve this exact full SHA-256 specifically
   for one catalog provider call. Record approval separately from the capture output.
   The newly printed hash is diagnostic metadata, not approval or a historical fingerprint.
   Never pipe it into a live invocation or auto-copy it as a supposedly approved hash.
   Baseline approval does not transfer to catalog. This implementation task authorizes
   neither live mode.

3. After that separate approval, start a new isolated process with the independently
   approved catalog hash and both explicit attestations:

```powershell
python -m tools.virtual_cmo_diagnostics --snapshot C:\Private\virtual-cmo-snapshot.json --run-id 3a8ae9035bb622ad9eb55a7b10d3e610991c829a1578ba02c6ff7030c855f0f8 --job-id 6c350338c84ffc5dbe212ae201906bc6 --mode catalog --expected-payload-sha256 APPROVED_CATALOG_SHA256 --catalog-hash-approved --authorize-one-provider-call
```

`--catalog-hash-approved` attests that the externally supplied expected hash received
separate catalog approval. The tool cannot authenticate a human approval record; operators
must retain it through their normal approval procedure. Without the hash, this attestation
or one-call authorization, a live catalog invocation fails before restoration/provider
access. There is no code path that promotes a freshly captured hash to an approved one.
Each command selects only catalog and permits at most one POST. A later baseline or
catalog attempt requires its own approval. Catalog is an augmented current reconstruction,
not an exact replay of the historical catalog-free dispatch.

The returned raw response stays in memory and passes the original executor JSON Schema and Pydantic. Catalog mode now applies [explicit numeric citation binding policy](virtual-cmo-numeric-binding.md), then repeats the same schema/Pydantic checks before original support, numeric semantics and normalization. Baseline retains the original rejection of uncited numeric context. Record the build HEAD alongside the payload hash: the wire hash alone does not identify the server acceptance policy. Only then are original Quality Gates evaluated with accepted ancestors. No result is persisted. Reports contain only booleans, call count, closed stage/rule/reason and bounded zero-based positions. Provider/codec/SQL exceptions are replaced by fixed safe codes; the CLI disables transport/SQL logging. HTTP/model failures stop immediately; a new attempt requires new permission. Successful schema validation alone does not imply gate acceptance.

## Verification and remaining uncertainty

`tests/test_virtual_cmo_diagnostics.py` uses the real executor and production adapter with mock HTTP, verifies both modes and exact selected-mode wire bytes, rejects a second POST even across client instances, enforces separate catalog hash approval, rejects mode mismatch and wrong source/payload fingerprints before HTTP, checks schema and closed numeric semantic rejection, proves Quality Gates execute and still reject, and verifies safe output and read-only restoration. No live OpenAI request is needed. Historical output remains unavailable, so replay success cannot identify or disprove the exact old violation. Hashes are diagnostic metadata and should still be kept within the intended operational audience.

