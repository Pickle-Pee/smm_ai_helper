# POSITIONING observation grounding

The qualitative observation check is intentionally stricter for future executions.
Previously a statement could cite an authorized source while adding an unsupported
competitive alternative or market expectation as OBSERVATION. Source identity and
Quality Gates alone did not establish that the text was supported.

## Authoritative acceptance

Existing source identity, seed, differentiation and local product-truth guards
retain their precedence. The numerical guard runs next, unchanged for every kind.
An OBSERVATION then requires its entire statement text to occur literally within
one actually cited local source, or within the assertion text of an actually cited
accepted parent of kind FACT or OBSERVATION. A source may contain surrounding
context; paraphrases and assertions assembled across sources do not qualify.
Parent hypotheses, inferences and recommendations cannot be promoted to observed
facts by quotation. Existing `supported_text` and `assertion_support` decoding keeps
strategy numeric-context quotes and serialized technical fields out of parent
assertion authority. No source is inferred, added or substituted.

The bounded diagnostic is `observation_support_required`; numeric failures still
report `numerical_support_required` first. This check is a conservative quotation
policy, not independent verification of an owner's assertion or model quality.
Unsupported qualitative reasoning may remain an explicitly typed hypothesis,
inference or recommendation, subject to all existing output-specific guards.

## Provider generation subset

The canonical Pydantic schema, persisted payload version, public DTOs and complete
kind enum remain unchanged. Direct canonical validation still accepts a genuinely
supported OBSERVATION. The provider receives a deep copy with OBSERVATION removed
from every finite statement-kind enum, including complete support branches.
INFERENCE, HYPOTHESIS and RECOMMENDATION retain their prior availability; outputs
already requiring HYPOTHESIS retain that singleton constraint. This intentionally
narrows generation and is not a structurally equivalent schema projection.

This applies with projection disabled or enabled and with explicit product-support
wire enabled. The diagnostic minimal-schema experiment also receives the same
three-kind restriction, although its separately retained raw builder is primitive
and unconstrained. Source floors, IDs, product-selection decoding and other bounds
are untouched. Unknown kind shapes fail before model dispatch, without fallback.
The change adds no full-object union, text repair, relabeling or output removal.

## Compatibility and verification

Existing stored artifacts remain readable and need no migration. Revalidating an
old unsupported OBS through the new executor can now fail by design. Only the explicit diagnostic `capture_request` control bypasses the provider kind
subset when requesting the original canonical baseline; its minimal variant uses
the current subset. This control supports experiments changing one variable and
must not replace the production executor. `capture_wire` still uses the real
adapter serialization, and production/immutable-image probes use the actual
executor hook. Current instruction capture goldens change; historical incident records remain evidence
of their original revision and must not be rewritten as current measurements.
Two synthetic category/points-of-parity regressions accepted before this change
and failed the new expected-rejection tests. Focused offline coverage also checks
actual cited factual/local quotations, hypothesis laundering, uncited sources,
numerical and source guard precedence, all seed states and provider modes,
immutability, pre-dispatch refusal, and the mocked production HTTP adapter.
No live provider or production acceptance follows from those offline checks.
