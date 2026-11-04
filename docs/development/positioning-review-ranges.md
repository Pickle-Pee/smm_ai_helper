# POSITIONING independent review: token_ranges.v2

The immutable canonical draft remains server-owned. The verifier receives a
lossless numbered token table for each output and selects half-open token ranges.
It never reproduces the draft or source quotes. A hash binds the report to the
exact draft, citations, evidence and contract version. No Unicode normalization
or UTF-16/byte offsets are used. The server resolves ranges into original text.

Reports are keyed by exactly the requested output names. Each output has its
own closed source-ID enum, limited to its existing citations and available
authorized sources. Complete source quotations are resolved by the server.
Ranges can overlap: several atomic propositions can occupy one sentence.
The union of ranges must cover every token. `atoms_complete` is a separate
semantic judgment; token coverage cannot prove extraction recall.

APPROVE cannot authorize arbitrary free prose by labeling it HYPOTHESIS.
Facts require the complete exact assertion from an eligible cited source;
demonstrations remain RTB-only. Nonfactual strategy uses a positive closed
prospective-language contract (`positioning_strategy.py`), supplied to generation.
Other wording fails closed, including valid paraphrases outside that contract.
Production string identities enable request-scoped proposals for the actual
category, task, value, tentative difference and full positioning sentence. Exact
product/audience slots and each required source ID must match this request and
be cited. Feature-specific angles are enabled only by closed complete owner
source patterns; unknown prose enables a prospective generic angle, never a new
feature. Offer/RTB still carry complete exact source conditions. The
source-role taxonomy is extended with product identity, which is not proof of
product properties. Source roles are enforced by output independently of labels.

This restriction can reject useful strategy. Relevance, section purpose and
usefulness remain independent acceptance criteria; template membership is not
proof of production quality. `output_fulfilled` must be true for every output in
addition to `atoms_complete`. A safe research task that fails to supply the named
positioning output must block acceptance. Numeric/overlong identity slots cannot
be interpolated into mixed strategy; existing numeric guards remain unchanged.

Known factual-premise detectors provide additional diagnostics and scan the
whole row to prevent splitting a risky phrase across atoms. Their negative
result never grants approval. An independent review reproduced an arbitrary
accreditation claim passing the earlier negative-word-list approach; the positive
strategy contract closes that class of bypass.

`verification_inputs()` reconstructs evidence using the executor's identities.
Evidence-backed factual competitor/market parents may be cited only by their
existing parent claim ID. Hypotheses and parents with missing evidence records
are excluded. No new competitor source or product property is inferred.

Fulfillment is tri-state: `requires_follow_up=True` is established only by a
closed complete owner-source pattern for delayed collection, optionally with
the exact materials/firing prefix. Ambiguous/legacy prose yields `None`, never
False. `fulfillment_guarantee=unavailable` explicitly records that limit.
Known no-further-action promises are checked on the complete draft independently
of auditor labels. This is a bounded invariant, not general source entailment.

Persistence tables and canonical result schemas do not change. Existing accepted
artifacts retain their historical semantics. Old in-flight responses cannot be
replayed across changed generator/verifier instructions, evidence or schemas:
the existing payload/draft hash mismatch blocks recovery without another POST.
Same-revision recovery replays saved text/receipt, including the independent
review, without repeating either successful call. Unknown outcomes remain
terminal and cannot be reclassified as successful or free.

For new acceptance runs, process-local HTTP timeout 120s is valid with the
existing graph wall deadline 300s and lease 330s. Both generation and verification
share the graph's absolute deadline. HTTP timeouts cover transport inactivity,
not a guaranteed 120s wall allocation. Defaults and rollout flags stay unchanged.
