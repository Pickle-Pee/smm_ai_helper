# EXPERIMENTS provider schema projection

`EXPERIMENTS_SCHEMA_PROJECTION_ENABLED=false` is the production default. The
composition root injects it into EXPERIMENTS only; POSITIONING retains its own
independent switch and implementation. No migration or persisted contract changes.

PR #115's controlled replay held `gpt-5-mini`, instructions, input and the 16000
output budget constant. Baseline returned `incomplete/max_output_tokens`, empty
output and zero usage; removing annotations returned `completed` (41501 input,
4571 output, 256 reasoning tokens). Reported schema size was 7199 → 6431 bytes.
This motivates a disabled candidate, not a proven general root cause or rollout.
Canonical compact sorted JSON sizes in production metadata may differ from those
reported with default JSON spacing; compare hashes using the same convention.

`BaseExecutor.generate` owns the original `validation_schema`, constructs its
Draft 2020-12 validator before asking `provider_schema_for` for an independent
wire schema, and retains the original for response validation. EXPERIMENTS calls
`strip_schema_annotations` from production code (no `tools/` imports). It removes
only `title`, `description`, `default`, `examples` at known schema positions,
including definitions and conjunction/alternative branches. It does not traverse
enum/const/default/example literals or extension data. Property/definition names
matching annotation names are preserved. Boolean schema nodes are preserved.

Assertions, required fields, references, evidence/parent support branches and
length/array bounds stay identical. Both schemas must pass schema validation and
finite JSON serialization. Custom dialects/vocabularies, scope-changing IDs,
dynamic/external references and references into removed annotations or literal
data are refused with a bounded `SchemaProjectionError` before model I/O; no
fallback, repair or retry is introduced. The supported generated schema uses
retained local definition references. Original schema is never mutated.

Server response processing is unchanged: original JSON Schema, Pydantic,
canonical coverage, support identity/provenance, semantic/numerical grounding,
ExperimentDesign strategic parent subset/uniqueness, exact supplied constraints,
normalization and the outer Quality Gates. Every canonical output still cites an
eligible accepted VIRTUAL_CMO/POSITIONING hypothesis. Missing strategic parents
still block generation. No model, Expert Core, input, output budget, retry policy,
graph, executor lifecycle or serialized payload version change.

Logs contain enabled/applied, removed annotation count, original/provider bytes
and SHA-256 of canonical compact sorted UTF-8 JSON only. They contain no schema,
request/response, business values, evidence IDs or execution identity. Disabled
mode reports equal hashes/bytes, applied=false and zero removals.

The diagnostic CLI explicitly constructs an unprojected EXPERIMENTS executor;
its baseline remains the original contract even with both production flags true.
Read-only restoration and live-call opt-in rules are unchanged.

Verification: `python -m pytest tests/test_experiments_provider_projection.py
tests/test_experiments_diagnostics.py tests/test_positioning_provider_projection.py`.
Run the repository's full Python and container-smoke CI jobs for the final commit.
Tests compare complete real-adapter HTTP bodies with mock HTTP transport, exercise
16 outputs and three designs through full acceptance, invalid schema/semantic
responses, isolation, safe logs, constraints and fail-closed behavior.

For the separately authorized single replay and rollback, follow
[verify-experiments-projection.md](../runbooks/verify-experiments-projection.md).
