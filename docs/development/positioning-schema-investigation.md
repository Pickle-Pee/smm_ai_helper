# POSITIONING: isolate the Structured Outputs schema failure

Date: 2026-10-12. Base: current `master`, `0376738` (PR #111 merged).
Scope: standalone diagnostic tools, offline tests and report. No production
contract, Expert Core, Quality Gate, model, budget, retry or DB state changes.
No real provider request was made in this investigation.

## Evidence boundary

The operator reports three production `incomplete_empty_max_output_tokens`
failures with zero usage and empty output for run
`24387ccc7a22b01fc6bcd8189686221826ff3b1002e04f54baabcb6194bf72c7`, job
`be9baf5c41a98c4d870c4850d0f9297a`. Subsequently:

| Diagnostic case | Reported result |
| --- | --- |
| baseline | Same empty zero-token incomplete response |
| no_core | Same failure |
| small_context | Same failure |
| simple_schema | completed; input=15260, output=3184, reasoning=256 tokens |

Successful correlation ID: `req_68da70aff5f142f694db4d2d2b1ee16f`.
These are operator-supplied observations, not new API calls or independently
retrieved provider traces. The original instruction/input/schema sizes were
53151/22827/8048 UTF-8 bytes; model `gpt-5-mini`, budget 16000.

Schema is now the strongest direction to investigate: the successful ablation
kept instructions, business input, model and budget but relaxed several schema
features together. This does not identify a single failing keyword, prove grammar
incompatibility, prove causation from one success, or validate the business output.
Provider/compiler defects and intermittent behavior remain plausible. A normally
unsupported schema should produce a request error; the zero-token incomplete
envelope is not itself a precise schema-validation diagnostic.

**Exact incident schema limitation:** no incident snapshot, schema fingerprint or
production read-only connection was available here. The 8048-byte schema alone
does not reveal seed presence, support IDs/counts or the precise selected subtype.
Measurements below are explicitly synthetic generator reconstructions. To inspect
the exact run, use the new schema-only mode against its approved snapshot or the
existing read-only PostgreSQL reader. Compare the incident-compatible deployed
revision, dependency versions, instruction hash and input/schema sizes before
interpreting results. Never export or print the original schema.

## What production actually constructs

`PositioningExecutor.output_type_for` selects one of four Pydantic output types,
depending on the optional customer-job and alternative seeds. All contain a
strict object with required outputs/assumptions/limitations. Outputs is a bounded
array whose item has an outer `anyOf`: two subtype refs with both seeds, four with
one or neither seed. Output-name sets separate the branches; each subtype encodes
allowed kinds (including forced hypotheses without seeds and for differentiation).
They are not a root-level union. There are no `type: [..]` nullable unions in the
currently generated POSITIONING schemas.

Every statement definition also has sibling object constraints plus a nested
`anyOf` of complete copies of that object, each making one support array nonempty.
This comes from `OutputStatement.__get_pydantic_json_schema__`. Unlike the outer
output-name union, the support branches overlap when both arrays are nonempty.
That overlap is valid JSON Schema (`anyOf`, not `oneOf`). It adds another OR level
and repeats object fields, enum/const restrictions, lengths and required sets.

`support_response_schema` makes local evidence and accepted within-scope parent
claim IDs request-owned string enums in shared `AllowedEvidenceId` and
`AllowedParentClaimId` definitions. Array items refer to those definitions.
With no parents, it removes the impossible parent-support branch and caps the
parent array at zero; the remaining support `anyOf` has one branch. It also scopes
the surviving copied branch. No fabricated or caller-declared parent support is
introduced. Each family is capped at 250 IDs; aggregate enum/string limits are
checked before calling the provider. This validation is JSON Schema validation
and application bounds checking, not proof of OpenAI strict compatibility.

Other current constraints: outputs minItems=1/maxItems=32; support arrays maxItems=32
(or zero for an unavailable family); assumptions/limitations maxItems=12;
text minLength=1/maxLength=4000; references minLength=1/maxLength=128.
Enums constrain output names, kinds and confidence; singleton hypothesis kinds
are emitted as `const`. `$ref` sites are local/acyclic in the tested generator
variants. Object fields are required and additionalProperties is false in outer
and copied branch objects. Tests demonstrate satisfiable synthetic examples and
no contradictory length ranges; they do not prove the historical instance.

## Current documented subset versus this generator

Official documentation checked on 2026-10-12:
[Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs#supported-schemas),
[GPT-5 Mini](https://developers.openai.com/api/docs/models/gpt-5-mini).

GPT-5 Mini supports Structured Outputs and Responses, and is not a fine-tuned
model. The guide permits nested anyOf, definitions and refs, provided each branch
fits the subset; root must be an object without anyOf, all fields required, objects
closed. It explicitly lists array minItems/maxItems. Limits: 5000 properties,
10 nesting levels, 1000 enum values, 120000 schema-name/enum/const characters;
a string enum above 250 values has a 15000-character limit. The guide lists
unsupported compositions including allOf/not/conditional/dependency keywords.
It excludes string lengths for fine-tuned models; its base string-constraint list
does not explicitly promise minLength/maxLength. That omission is uncertainty,
not evidence that these keywords are universally forbidden for base GPT-5 Mini.

The current generator passes the structural requirements in synthetic fixtures,
has none of those explicitly forbidden compositions, and uses documented array
bounds/ref/union concepts. Nonetheless, nested overlapping support branches,
sibling constraints, string lengths and singleton const must be tested on the
actual model/backend. The tool always reports provider_compatibility=not_verified;
Draft202012Validator success is never promoted to provider compatibility.

## Offline measurements

Synthetic fixtures have one short local identity and zero/one short parent identity:

| Seeds | Parent support | Bytes | defs | anyOf nodes | refs | property occurrences | enum values |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Both | No | 4189 | 3 | 3 | 6 | 27 | 57 |
| Both | Yes | 5940 | 4 | 3 | 14 | 39 | 86 |
| Neither | No | 7285 | 5 | 5 | 12 | 51 | 73 |
| Neither | Yes | 10388 | 6 | 5 | 28 | 75 | 110 |

Raw counts include copied branches and definitions once. Reachable counts/depth
expand local refs and exclude unused definitions. Maximum reachable anyOf depth
is 2; JSON container depth is 4 (root object, outputs array, statement object,
support array). Combinators constrain the same JSON instance and do not themselves
add container levels. Fixture string-character totals are 947–1999, below the
documented cap. Real IDs/counts change these measurements. Do not infer the exact
incident schema or token cost from a byte-size match.

## Single-group matrix: first tests and why

Every new case starts from an independent deep copy of the original production
payload, changing **only** `text.format.schema`. System/user strings, model,
reasoning=low, generation budget, strict=true and format name are preserved.
Existing broad PR #111 cases remain available for compatibility; use
`--schema-only` to exclude instruction/context/model ablations from this matrix.

| Priority / case | Sole logical group changed | Interpretation and limitation |
| --- | --- | --- |
| 1: schema_no_support_anyof | Remove only complete-object support ORs; retain outer subtype union, refs, enums and other bounds | Most distinctive composition and source of repeated constraints. With no parents, removes redundant single-branch OR. Loosens required support; server checks must still reject unsupported statements. |
| 2: schema_no_string_bounds | Remove only minLength/maxLength in schema positions | Test uncertain string-keyword support cheaply without changing enums/OR/cardinality. Does not claim these keywords are forbidden. |
| 3: schema_no_support_enums | Remove only support-identity enum constraints in their shared defs | Isolates request-specific allowlists while keeping refs and semantic enums. Tests identity-related constrained decoding. No IDs may be trusted from resulting output. |
| 3: schema_inline_refs | Replace local acyclic refs with equivalent schemas; remove definition representation | Keeps validation language, tests ref processing. May expand schema/enum totals and itself exceed a documented limit; inspect metadata first. Remote refs, cycles, conflicting siblings and excessive expansion fail closed. |
| 4: schema_flatten_output_union | Merge outer output-name/kind subtype choice into common name/kind enums | Retains support OR and other constraints but loses name-kind correlation. Original defs stay intact to isolate outer selection; a backend may still process unused defs, so failure is inconclusive. |
| 5: schema_no_array_bounds | Remove only minItems/maxItems | Distinguishes cardinality/empty-family interactions from OR/ref representation. These are documented for base models; broad removal also relaxes support floors and empty-family caps. |
| 6: schema_no_semantic_enums | Remove only output_name/kind/confidence enum/const constraints | Tests categorical constraints independently of support IDs; loses critical semantic enforcement on the wire. Server validation remains mandatory. |
| 7: schema_no_annotations | Remove only title/description/default/examples | Checks metadata/grammar-size sensitivity without changing the accepted output language in current fixtures. Lower priority than semantic/composition constraints. |

Recommended first separately authorized batch: baseline, no_support_anyof,
no_string_bounds, no_support_enums (four calls maximum). If all fail, compare
baseline/ref expansion/outer union/array bounds in another authorized batch.
This document is a plan, not authorization or an executed experiment. Single
positive comparisons require separately approved paired repeats to assess
intermittency. Do not combine multiple removals until individual factors are
measured; combined successes cannot identify the responsible group.

## Tool and safety

```sh
python -m tools.positioning_diagnostics --schema-only --snapshot /secure/incident.diagnostic-snapshot.json --run-id RUN_ID --job-id JOB_ID
```

Offline stdout contains only safe counts, closed flags, byte sizes and canonical
SHA-256 hashes. `schema_structure` describes the baseline; `schema_matrix` reports
each new schema's measurement, structural counts and whether it differs;
`matrix` contains full-payload measurement pairs. No definition/property names,
refs, enum values, schema contents, prompt/business text or keys are printed.
The walker visits schema locations only, excluding dictionaries inside enum,
const, default or example literals. Hashes use the existing canonical sorted-key
UTF-8 JSON convention, not raw HTTP framing.

Snapshots and restored graphs reuse PR #111 identity/acceptance validation.
Optional `--database-read` still begins with REPEATABLE READ READ ONLY, never
claims JobExecution and never writes or wakes work. No modifications to those
paths or to the provider call policy are included. `--live`, explicit `--case`
and `--max-calls` remain jointly required, hard maximum four calls per invocation,
no retries. `--schema-only` rejects legacy non-schema live cases before reading
data. Nothing in offline inspection performs a live model call; relaxed diagnostic
outputs are never accepted/persisted into the production graph.

Ref expansion has a 50000-node budget and rejects remote/cyclic/conflicting
references rather than silently weakening constraints or fetching documents.
Recursive refs can be valid for Structured Outputs; refusal to inline one is a
tool limit, not evidence of provider incompatibility. Schema limit flags describe
documented measurable bounds only, not a complete subset implementation.

## Minimal fix plan, separate from this PR

1. Restore and fingerprint the exact incident request; obtain safe structural
   metadata. Verify selected seed variant and support family counts. Require the
   deployed schema hash/size or incident-compatible code/dependencies before
   treating the reconstruction as historical proof.
2. Run only separately authorized schema pairs with unchanged input/model/budget;
   correlate all response IDs with provider-side compilation/accounting traces.
   Identify the smallest implicated restriction group. If no stable distinction
   appears, investigate provider/backend behavior rather than choosing a broad
   lax production schema based on one successful `simple_schema` call.
3. If evidence isolates support OR or a keyword group, project **only that group**
   out of the provider wire schema. Keep one authoritative full validation schema,
   produced by the current output type and support builder, for server validation.
   In `BaseExecutor.generate`, full-schema Draft validation must keep using the
   original schema; the projected copy belongs only in model_call.response_schema.
   Do not reassign the schema currently used for both wire generation and validation.
4. Preserve Pydantic parsing, exact output-name coverage, support identity checks,
   evidence/parent reference checks, nonempty support, seed hypotheses,
   differentiation hypotheses, product-truth RTB/offer requirements, provenance
   construction and Quality Gates. No persisted/public contract migration should
   be needed for this narrow provider projection, but recheck the final diff.
5. Add adversarial regression cases where the relaxed provider schema accepts
   unknown support IDs, absent support, wrong kind/seed behavior, excessive bounds
   or incomplete/duplicate outputs; the full server contract must reject them.
   Perform any live semantic/quality acceptance only with separate authorization.

No projection or production fix is implemented here. Evidence could instead
implicate a backend grammar defect; handle that confirmed condition separately.

## Verification

Offline tests cover all four seed-dependent schemas with/without parent support,
every single-group variant, source/cross-variant independence and invariance of
the production payload outside schema. Semantic witnesses demonstrate each intended
relaxation, while representation-only cases preserve acceptance/rejection on
adversarial fixtures. The flattened differentiation observation still fails
existing server semantics. Remote/cyclic/conflicting refs and sensitive literal
content have safe rejection/metadata tests. CLI subprocess tests block real HTTP
clients and DB sessions in both default and schema-only modes. Existing read-only,
live opt-in/call cap, architecture and production regression tests are retained.
Full exact-HEAD CI and container-smoke results are recorded in this PR.
