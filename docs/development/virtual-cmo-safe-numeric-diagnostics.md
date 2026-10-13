# VIRTUAL_CMO safe numerical diagnostics

Baseline: master after PR #119, 9ff88255ae7b3006c026c4e30365e96b16a2ebf2.

This implements the diagnostic stage described in the reliability architecture
proposal. The historical provider response is unavailable; these observations
cannot establish its root cause. Parsing exactness, catalogue improvements and a
durable summaries table were proposals for subsequent, independently justified
changes. None is implemented here.

## Boundary and behavior

BaseExecutor calls an isolated rejection observer after the existing checks have
established a failure. Only VIRTUAL_CMO numerical semantic failures emit
the fixed event virtual_cmo_numeric_rejected with policy numeric_diagnostics.v1.
Earlier JSON/schema/reference failures keep their original stages and do not
receive a numerical classification. Text/items numerical rejections report their
original location with quote relations not_checked.

The observer receives the original decoded response dictionary (before Pydantic
and binding), the final parsed representation, the original error, and the exact
local/parent maps used by validation. Binding in PR #119 works on a copy, so
the original quotes remain available at matching zero-based output/context indices.
Diagnostics never change the response or the original error. NumericContext still
strips edge whitespace, including the existing acceptance of explicitly cited
quotes that become exact after stripping. Accepted outputs are not scanned.

Only context_units and parent_context_units extract quotation channels.
No source inventory, prompt, catalogue, binding or grounding policy is changed.
Authorization, accepted parent status and scope remain owned by scoped_facts and
parent_claims. Website metadata and internal serialized identities are not quote
channels. An uncited but authorized selected source can be observed; that does not
authorize its citation. Family collisions are explicitly conflict. The validator's
local-before-parent citation precedence is preserved for selected comparisons;
an identical ID in another family is not classified as another source.

## Event fields

The event contains execution_id, original stage/rule/reason/location, zero-based
output_index/numeric_context_index, catalog_enabled, source_family
(local/parent/conflict/missing/not_checked), citation (local/parent/both/absent/not_checked),
raw_equals_parsed (boolean or null), scan_complete, and capped source/unit counts.

selected_raw_* and selected_parsed_* report separate relations with the selected
source's authoritative full units. other_raw_exact and other_parsed_exact report
exact equality with another authorized scoped source (across either family).
All relations use match, no_match, incomplete or not_checked:

- exact: full-unit equality.
- fragment: a nonempty proper quote substring of a full unit.
- edge_whitespace: unequal strings become equal after strip.
- line_endings: unequal strings become equal after CRLF/CR to LF conversion.
- nfc: unequal strings become equal after Unicode NFC normalization.
- nbsp: unequal strings become equal after NBSP to ordinary space conversion.
- json_escaping: quote equals the contents of a single JSON-encoded unit string,
  with ensure_ascii either true or false, while differing from its decoded unit.

These are independent observations, not repair suggestions or causes. The
transformations are applied only to whole units in diagnostics. Normal JSON wire
escaping preserves decoded equality and does not itself indicate a difference.
Representation comparisons apply to the selected source only; other-source
search reports exact equality only. No similarity ranking or reconstruction occurs.

## Work limits and isolation

Each failure scans at most 64 sources and 256 eligible units. If the authoritative
local evidence tuple exceeds 64 entries, the observer returns the unavailable
summary before constructing a local lookup map; this bounds diagnostic setup
as well as traversal. This fallback does not imply that sources are missing or
citations absent. Missing/ambiguous selected sources have not_checked relations. Before invoking an
extractor it preflights a source, charging a shared budget of 2048 value nodes and
65536 Unicode characters, with maximum nesting depth 32. This also bounds walks
through ineligible/non-numeric leaves and serialized parent claim parsing.
Character rather than byte accounting bounds UTF-8 payload memory by at most four
bytes per character. Extractor output is separately capped; no diagnostic cap
limits the authoritative validator or catalogue.

The selected family/source is scanned first. A positive observation remains match
even if later scope scanning is incomplete. A negative is no_match only for a
completely scanned population. A completed selected-source scan can therefore
report no_match while another-source search reports incomplete. Exhausted
preflight/unit/source budgets produce incomplete, never an unearned no_match.
Counts describe successfully preflighted sources and consumed units, not totals.

Classifier exceptions discard their messages, chains and tracebacks and emit an
empty safe summary with scan_complete=false and relations not_checked. Observer
and logging exceptions are contained by the rejection boundary. Logging failure
may lose the event; it never affects the original failure or triggers retries.
The sanitized outward exception and existing worker lifecycle are unchanged.
There are no additional provider calls, shared request state, accepted artifacts,
Quality Gate inputs, confidence/lineage/attribution changes or persistence writes.

## Correlation and persistence decision

GraphExecutionService.load_work constructs request.execution_id from item.job_id.
The event's execution_id therefore joins by exact identity to the existing
Graph claimed / Graph attempt failed job_id and run_id fields. Concurrent events
are joined by that identity, never by timestamp proximity. Direct invocations
report their actual execution_id only; no graph run is inferred for them.

The graph job can span attempts. No attempt number is available in the module
request, and lease claim_token is deliberately never logged. These diagnostics
do not promise durable attempt identity, lease-fenced persistence or a completion
transaction. They observe execution, including a worker that could later lose
its lease, rather than claiming an authoritative terminal state.

Existing application logs are sufficient for the requested observational event
and job/run correlation. They survive a Python process restart only to the extent
that the deployment's existing log collector/container storage retains them.
The repository does not guarantee an application log retention period or durable
query API; deleted/rotated logs and handler outages can lose summaries. Retention,
access and cleanup follow the existing operational logging policy. No requirement
here demonstrates the need for a durable, atomic, attempt-specific audit record,
so no database schema/migration is added. If that requirement is established
later, the architecture proposal's lease fencing, attempt identity, atomicity,
idempotency, retention, cleanup and rollback must be designed in that separate
persistence change. Rolling back this PR removes only the observer and event.

Only explicit allowlisted fields enter LogRecord arguments; no quote/source text,
support/fact IDs, business content, raw response, content hash, credentials or
exception objects enter logging extras, messages or traceback data. Do not enable
HTTP body capture or exception-local tracing. This observer adds neither.
Synthetic redaction tests inspect LogRecord fields and formatted outward
exceptions, including deliberately hostile diagnostic exceptions.

## Verification

tests/test_virtual_cmo_safe_numeric_diagnostics.py exercises both catalogue modes,
all numeric reasons (including model_construct-only impossible-schema reasons),
exact/fragment/wrong-source relations, raw/parsed stripping, Unicode/NBSP/CRLF/JSON,
family collisions, excluded sources, budget exhaustion, safe fallback, redaction,
concurrency and terminal graph failure. Existing numerical, transport, binding,
Quality Gates and graph lifecycle suites remain required regression coverage.
All fixtures are synthetic; no production or live LLM access is used.
