# POSITIONING product support wire v2 — review candidate

Baseline: `0441c49e3938c962f5165adae4f96916df164e1a`. This change is independent
of diagnostic Stage A. No production activation is included. Existing executor
construction defaults to `product_support_wire=False`; explicit constructor
injection selects v2 for offline tests and a separately approved rollout.

## Authoritative policy and execution

`executors/product_support.py` owns PRODUCT_OUTPUTS (RTB, value_proposition,
positioning_statement, offer) and PRODUCT_CATEGORIES (product_truth,
existing_proof). The original Positioning semantic validator uses the same policy.
Kinds do not change the grounding requirement. Other outputs retain their seed,
differentiation, evidence and parent semantics.

All four request-selected Pydantic output types retain their original authoritative
v1 schema. A separate v2 wire schema narrows product names out of every ordinary
complete-object branch, then adds a disjoint PositioningProductStatementV2 branch:

```json
{
  "wire_contract_version": "positioning.wire.v2",
  "outputs": [{
    "output_name": "RTB",
    "text": "Synthetic finding",
    "kind": "HYPOTHESIS",
    "confidence": "MEDIUM",
    "product_support_id": "<explicit choice from AllowedProductSupportId>",
    "evidence_ids": [],
    "parent_claim_ids": []
  }],
  "assumptions": [],
  "limitations": []
}
```

AllowedProductSupportId is an exact sorted enum of this request's authorized local
truth/proof evidence IDs, derived from the same evidence objects as AllowedEvidenceId.
Parent IDs, arbitrary local evidence categories and invented identities cannot
satisfy this scalar. It is mandatory for all four kinds. No contains/minContains,
conditionals, uniqueness keywords or cross-field equality extension is used.

Pipeline: strict JSON parse (duplicate-key, finite-value and size guards) -> exact
v2 wire schema -> explicit decode -> original exact v1 request schema -> original
Pydantic -> existing result/identity/support/semantic validation -> Quality Gates
at the unchanged caller boundary. Decode maps the model-selected scalar to one
lineage citation, followed by its additional evidence. It never searches for a
replacement, chooses truth for the model, fabricates an ID, falls back to v1,
repairs a rejection, or retries. Repeating the scalar in additional evidence is
rejected. Additional local evidence has 31 slots, preserving the original total
32 after mapping; parent references retain 32 slots. NormalizedClaim's existing
canonical sorting of lineage IDs is unchanged.

## Provider compatibility evidence

Official OpenAI documentation, fetched 2026-10-18:
[Structured Outputs supported schemas](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses).
The design uses documented object/array/string/enum, nested anyOf and local refs;
strict objects require all fields and forbid extra properties. Current documented
standard-model string/array bounds match the existing contract. Fine-tuned models
have additional unsupported bounds; they are outside this proof. Repository
default DEFAULT_TEXT_MODEL_HARD is the standard `gpt-5`; model selection is unchanged.

Tests enumerate the complete emitted keyword set, strict object properties and
root shape. Per-request enums remain shared refs. The optional existing provider
projection is tested both off and on; only its already-proven equivalent collapse
is used. The actual adapter serializes the strict schema through HTTPX MockTransport.
All four seed states complete original validation and Quality Gates offline.

This is a proof against the documented subset and bounded generated schemas,
not a live provider/compiler certification. No real OpenAI POST was authorized or
performed. No provider failure is reconstructed from a missing production response.
If a future target model/provider rejects this subset, stop activation and record
the blocker; do not broaden schemas or silently downgrade contracts.

`positioning-product-wire-measurements.json` records 12 synthetic profiles and
their original, wire and projected fingerprints, bytes, enum counts, string
budgets, object properties and expanded nesting. Maximum wire size is 109675
bytes, enum count 871 and counted strings 98204 characters. Allowlist bounds are
250 local + 250 parent identities, at most 128 characters each (the persisted ID
grammar is narrower). Schema budgets remain 1000 enums / 120000 characters;
fixed model shapes are checked against 5000 properties / depth 10. No truncation.
Reproduce from the repository with the test interpreter:
`python -m tests.positioning_product_wire_report` (offline, synthetic fixtures).

## Contract compatibility review

| Boundary | Compatibility evidence / behavior |
| --- | --- |
| Existing model calls | Default false retains v1 instructions, schemas, raw parsing and budgets; existing regression suites remain authoritative. |
| v2 model calls | Explicit version field; v1 responses fail under v2. No fallback or automatic conversion of missing selection. |
| Existing accepted results | Tests encode an accepted v1 result with an explicitly selected existing truth ID; decode retains precisely the same evidence set and parent references. Additional evidence slots are reserved without reducing the normalized total. |
| Persisted artifacts | `positioning.payload.v1`, executor key, result envelope and serialization are unchanged. Existing v1 and new decoded results roundtrip through actual result_to_json/result_from_json. No migration or historical writes. |
| Quality Gates / downstream | The normalized result contains the selected citation and all allowed extras/parents; fake HTTP integration passes full acceptance for all four seed states and projection settings. |
| Original validation | Tests prove whitespace rejected by original Pydantic, duplicate support rejected by existing result checks, coverage rejected, and corrupted mapping rejected by original semantic grounding. |
| Telemetry | Separate original-validation, v2-wire and projected-provider hashes; only closed metadata and identifiers. Private sentinels excluded. |

Actual production artifacts were not read or rewritten. Compatibility evidence is
structural and uses synthetic accepted results from the baseline contracts; it
does not assert inspection of every historical artifact or the original failed
response. Existing failed jobs and their evidence remain untouched.

## Regression matrix

448 cases = 4 output names × 4 kinds × 4 seed states × 7 support modes.

| Support mode | Expected |
| --- | --- |
| Explicit local product_truth | Accept |
| Explicit local existing_proof | Accept |
| Explicit truth + additional proof/other evidence + accepted parent | Accept; preserve every supplied reference |
| Explicit allowed local ID from wrong category | Reject at wire schema |
| Parent only, without explicit local product selection | Reject at wire schema |
| Missing selection/support | Reject at wire schema |
| Invented selection ID | Reject at wire schema |

The same expectations hold for OBSERVATION, INFERENCE, HYPOTHESIS and
RECOMMENDATION. Additional tests cover strict versioning, selected-ID duplication,
unknown extra IDs/parents, original validation defenses, bounds, full output sets,
artifact roundtrips, actual adapter serialization, Quality Gates and fingerprints.

## Rollout / rollback plan (not performed)

1. Independently review A and B separately; A can ship without B.
2. Keep production construction on v1 until B is approved. Inject
   `product_support_wire=True` explicitly through the production composition in
   a separately reviewed rollout change; do not conflate the existing equivalent
   projection flag with wire-version selection. Keep the same target standard model.
3. In separately authorized staging, perform one bounded provider acceptance
   check and require exact v2 response, original server/Pydantic/semantic checks,
   preserved lineage, full Quality Gate acceptance and safe correlated telemetry.
   Record actual model/schema fingerprints. Stop on rejection; no recovery calls.
4. Enable only new approved executions. Do not replay failed jobs, mutate evidence
   or migrate persisted artifacts. Observe closed error stages and reference mapping.
5. Roll back new generation by restoring v1 constructor selection. Existing decoded
   v1 artifacts remain readable. For an in-flight v2 call, complete validation with
   its selected contract or fail terminally; never reinterpret its response as v1.

This task stops for independent review; no production SQL, SSH, deploy, push, PR, merge or live
provider POST is part of delivery. Test outcomes are in positioning-contract-review.md.
