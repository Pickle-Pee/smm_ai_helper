# POSITIONING: equivalent single-support-anyOf collapse

Date: 2026-10-12. Base: `master` at `b9e601c`, after PR #112.
Diagnostic-only change. Production schemas, Pydantic models, Expert Core,
Quality Gates, retries, model and generation budgets are untouched. No real
diagnostic API requests or production deployment were performed.

## Evidence and candidate

Operator-reported live observations: baseline repeatedly returns
`incomplete_empty_max_output_tokens`; three independent relaxations complete:
no_support_anyof (3224 output tokens), no_string_bounds (3598), no_support_enums
(3463). The problematic schema has 5 anyOf nodes, 4 single-branch nodes,
13 local evidence IDs and zero parent IDs. These observations implicate schema
handling but do not prove a single defective keyword or compiler behavior.
They do not establish that the new equivalent variant completes.

Unlike removing support ORs, the new case
`schema_collapse_single_support_anyof` preserves their complete acceptance
predicate. Only provable single-branch support conjunctions are rewritten.
Two-branch support ORs, the output subtype union and unrelated single anyOf nodes
are preserved. There is no fallback to a relaxed/approximate schema.

## Local proof and refusal conditions

Let S be the parent schema without anyOf, B its only branch. The original
predicate is S AND anyOf[B], hence S AND B. For the generated support shape:

1. Both are fully required object schemas with the same properties and
   additionalProperties=false. Object keywords are restricted to this known
   profile; differing constraints or unexpected keywords cause a closed refusal.
2. After ignoring object title annotations and removing minItems only from
   evidence_ids/parent_claim_ids, the objects must be structurally identical.
   JSON-sensitive comparison distinguishes boolean true from integer 1 in
   enum/const values. It never treats merely similar constraints as equivalent.
3. For each support array, the intersection of lower bounds p and b is
   minItems=max(p,b), treating absent minItems as zero. Every other restriction
   already exists identically in S and B and remains in S. Contradictory floors
   are refused rather than approximated. A nonempty support floor must exist.
4. Ref scope/evaluation constructs ($id, anchors/dynamic refs, unevaluated
   keywords) are excluded from this proof profile. Ref equality alone would
   not justify a rewrite with different reference scopes.

Therefore the candidate accepts exactly the same JSON instances for this
recognized profile. Titles are annotations; the parent's title is retained.
The constructor validates both schemas with Draft202012Validator, but schema
well-formedness and finite tests are not the proof: the constrained structural
rule supplies the argument above. Provider compatibility remains `not_verified`.

With zero parent IDs, the retained branch requires evidence_ids.minItems=1.
This floor moves to the parent alongside the unchanged evidence allowlist/ref,
maxItems=32 and parent_claim_ids.maxItems=0. Empty support cannot become valid.
Semantic enums/const, text/reference bounds, output and limitation cardinality,
required fields and closed-object rules remain enforced. Shared identity enum
definitions remain byte-for-byte intact. Removing repeated branch copies reduces
physical occurrences of constraints, not the logical restrictions.

The rewrite works on an independent deep copy. Any unsafe target, including a
later target after earlier successful rewrites, raises the closed error
`single_support_anyof_not_equivalent`, suppressing validation exception context.
No partial candidate is returned and the caller's schema stays unchanged. With
parents available, support anyOf has two branches: the candidate is an explicit
no-op, with the same hash and changed=false. The transformation is idempotent.

## Offline before/after report

Fixtures use 13 synthetic 52-character local IDs and zero/one synthetic parent.
They are not an export of the production schema or business snapshot.

| Selected output type | Parents | Bytes before → after | anyOf before → after | Single-branch before → after |
| --- | ---: | ---: | ---: | ---: |
| PositioningOutput (both seeds) | 0 | 4888 → 3197 | 3 → 1 | 2 → 0 |
| PositioningWithoutJobOutput | 0 | 8040 → 4917 | 5 → 1 | 4 → 0 |
| PositioningWithoutAlternativeOutput | 0 | 8048 → 4925 | 5 → 1 | 4 → 0 |
| PositioningWithoutSeedsOutput | 0 | 7984 → 4905 | 5 → 1 | 4 → 0 |
| PositioningOutput | 1 | 6678 → 6678 | 3 → 3 | 0 → 0 |
| PositioningWithoutJobOutput | 1 | 11226 → 11226 | 5 → 5 | 0 → 0 |
| PositioningWithoutAlternativeOutput | 1 | 11234 → 11234 | 5 → 5 | 0 → 0 |
| PositioningWithoutSeedsOutput | 1 | 11126 → 11126 | 5 → 5 | 0 → 0 |

For the synthetic missing-alternative fixture (matching the previously reported
8048-byte size and 5/4 counts), canonical SHA-256:

- Original: `c43cb2a48f88f66790ab8756a4d0e9a5eced175f636e6d2995c97340e1fe745a`.
- Candidate: `dfcbf037b0c62b9a457686215f3a9565e64ad67d67baac87174265cfadcd2a2b`.

A byte-size/count match is consistent with that subtype under current code and
dependencies, but does not identify the actual production IDs/schema fingerprint.
The exact run snapshot remains unavailable here. For the four-branch fixture,
only the outer item union survives. Allowlist counts stay 13/0; object closure,
required sets and length-range consistency remain intact. With parents, every
original schema hash equals its candidate hash.

## Tool, safety and test coverage

The case is added to the existing standalone CLI and schema-only matrix:

```sh
python -m tools.positioning_diagnostics --schema-only --snapshot /secure/incident.diagnostic-snapshot.json --run-id RUN_ID --job-id JOB_ID
```

The offline report provides baseline/candidate schema byte sizes, SHA-256,
safe structural counts and changed flags. Each case modifies only
text.format.schema. Instructions, context, model, reasoning, strict format/name
and generation budget are identical; source and sibling variants are independent.
No schema contents, evidence values/IDs, business data, prompts or keys are printed.
Schema traversal ignores JSON literals inside enums/defaults/examples.

Existing PostgreSQL REPEATABLE READ READ ONLY, no JobExecution claims/writes,
live explicit opt-in, selected-case requirement, four-call hard cap and no retries
are unchanged. No live flag was used during this investigation. CLI subprocess
tests continue to block real HTTP clients and DB sessions. A hypothetical unsafe
single-support branch fails the entire diagnostic construction, before any live
probe is dispatched; it is never replaced with a relaxed case.

Tests cover all four seed-dependent variants with and without parents, using
13 local identities. Original and candidate validators agree on valid support,
support at bounds, empty support, parent-only/mixed support when available,
unknown/empty/oversized IDs, wrong kinds/output names/confidence, missing fields,
empty/oversized text, excessive output/support/assumption/limitation counts and
extra statement/root properties. Seed-dependent kinds are compared separately.
The assertion is JSON Schema acceptance equivalence, not a replacement for
additional Pydantic/result/provenance/Quality Gate validation.

Structural tests independently require the candidate to equal the original
schema with only single support OR removal and promotion of the evidence floor.
They preserve stronger pre-existing floors, check idempotence and unchanged
two-branch cases, and reject changed enums/bounds/required/closure/refs, extra
constraints, boolean/integer differences and scope/evaluation constructs.
Atomic failure, unrelated ORs and enum literals are covered. Full exact-HEAD
CI/container-smoke results are recorded in the PR.

## Production decision gate

No production fix is recommended yet. After separate authorization, pair the
exact incident baseline with this candidate using identical instructions,
context, model, reasoning and budget. Record only safe request IDs, schema hashes
and envelope/usage metadata; repeat authorized pairs to evaluate intermittency.
For schemas with parents this case is a no-op and cannot explain/improve failure.

Only if live A/B consistently distinguishes the equivalent candidate should a
separate production proposal consider the same guarded rewrite at the provider
boundary. The full original server schema, Pydantic parsing, provenance and
POSITIONING semantics must remain authoritative, with all regression/quality
checks retained. Until then this is an equivalent offline diagnostic candidate,
not a demonstrated remedy for Structured Outputs.
