# Owned-product evidence v1

This internal capability acquires descriptive context from one explicitly declared
owned/authorized public HTML page. It does not run a module or choose an execution
path. `BUSINESS_DIAGNOSTICS`, ModuleId, Registry 1.0/1.1/1.2, graph contracts and
production ingress remain unchanged. No schema migration or new persistent cache.

## Trust and authorization

`user-declared owned URL` ≠ `every website claim is verified truth`.

`OwnedSiteRequest(owned_site_url=...)` means the caller asserts permission to use
this source as its own business source. It does not verify ownership or page claims.
There is no first-URL, domain-name, LLM or leftover-URL ownership inference.
The service never accepts MarketingIntent.provided_urls as owned sources.

All acquired evidence uses the existing Quality Gates `EvidenceRecord` and
`EvidenceSourceClass.FIRST_PARTY`. Its provenance starts with
`Owned-site published claim; not independently verified` and includes source role
and final page URL. This expresses FIRST_PARTY_PUBLISHED_CLAIM semantics without
adding a global enum or changing existing serialization/quality policy. FIRST_PARTY
is source provenance, not independently verified truth. Quality Gates still checks
structural support, not semantic truth.

The caller owns authorization, extractor/provider configuration, and any explicit
confirmation. The capability must be explicitly composed; no default production
registration exists. Neither acquisition nor Copilot writes BrandProfile.

## Flow and public internal operations

`safe fetch -> structured snapshot -> provenance -> ContextResolver -> modules`

```python
from app.product_context import (
    OwnedProductEvidenceService, OwnedSiteRequest, build_owned_site_analyzer,
)
from app.product_context.projection import attach_acquisition

capability = OwnedProductEvidenceService(
    analyzer=build_owned_site_analyzer(), extractor=injected_structured_model,
)
acquired = await capability.acquire(OwnedSiteRequest(owned_site_url=explicit_owned_url))
# Keep acquired with the caller for review, source limitations and confirmation.
prepared = attach_acquisition(caller_authorized_copilot_request, acquired)
response = await copilot.execute(prepared)
```

`attach_acquisition` is a pure explicit caller operation. It adds owned_site_url
and deterministic owned_site_context to the immutable request. It rejects a result
for a different declared URL and replaces stale owned context with an empty layer
on acquisition failure. MarketingCopilotService performs no owned-source I/O.
The caller retains the complete acquired snapshot, including observations masked
by current facts. Snapshot persistence/review UX is not introduced in this task;
projected excerpts and provenance travel in the existing compiled context packets.

When an owned URL is declared, `competitor_url` / typed competitor scope for
comparative positioning, or `competitor_urls` for Strategy Builder, must be supplied
as explicit caller-authorized context. Raw URL order is ignored. Legacy competitor
handling for requests with no owned-site declaration is unchanged. Own pages never
go through COMPETITOR_ANALYSIS. Competitor page evidence remains EXTERNAL_PRIMARY
with its own generated identity, while any own business context is marked FIRST_PARTY
site_claim; it cannot satisfy the competitor executor's public-page evidence check.

## Snapshot and extraction contracts

All contracts are frozen strict Pydantic models with extra="forbid", instance
revalidation, bounded strings and immutable bounded tuples. Schema version:
`owned_product_snapshot.v1`.

| Snapshot field | Meaning |
| --- | --- |
| snapshot_id | Code-generated identity of source/text/extraction |
| owned_site_url | Original explicitly declared fetch target |
| canonical_url | Validated final response URL; not an untrusted HTML canonical/og link |
| page_title / page_title_evidence_id | Fetched title and its exact evidence reference, or null |
| statements | Up to 30 typed statements with code-generated IDs, kind, field, text and evidence IDs |
| evidence | Up to 91 minimal SourceExcerpt envelopes: existing EvidenceRecord, page_url, literal excerpt |
| unknowns | Missing observable fields, explicit unknown statements and research limitations |
| source_role / trust | caller_declared_owned_site / site_claim |

Statement fields are stated_product_service, stated_audience,
stated_customer_problems_jobs, stated_value_propositions, stated_features_capabilities,
stated_proof, stated_pricing, stated_geography, cta_conversion_path and
positioning_message_observations. Lists are bounded; no separate truth/economics
fields are introduced. Source quotes and statement text are at most 800 characters.

The extractor receives only fetched text segments and composed extraction
instructions/schema, using ExpertInstructionComposer once. It receives no caller
facts, decision selectors, technical IDs, web search or external knowledge. The
caller supplies a single-attempt structured model callback. Duplicate JSON keys,
unknown fields, excessive response size (>65536 characters), invalid shapes and
unsupported excerpts produce INVALID_EXTRACTION, with no partial projection.

| Kind | Required grounding | Projection |
| --- | --- | --- |
| OBSERVATION | Text equals a single literal quote, found in a fetched text segment | Safe descriptive slots only, always attributed as site statements |
| INFERENCE | Explicit interpretation and 1–3 literal supporting excerpts | Retained only in snapshot |
| UNKNOWN | Explicit unknown, no evidence references | Retained only in snapshot/unknowns |

Pricing and geography cannot be inferences. An observation such as “We are №1”
remains a quote attributed to the site; it never becomes “the company is market
leader”. Real profitability, CAC/LTV, satisfaction, uniqueness, buying reasons,
market share and website effectiveness remain unknown without other evidence.
Source matching prevents fabricated quote text, not misleading excerpt selection
or semantic misclassification. Model instructions preserve qualifiers, negation,
units and dates; exact quotes remain reviewable. No semantic-truth verifier is claimed.

## Projection and confirmation

Deterministic projection creates existing ContextEntry / AuthorizedContextFact
records. Product, audience and job observations fill `product`,
`target_or_target_hypothesis`, and `customer_job_or_need`. Other observations use
owned_site-prefixed descriptive keys. Each value retains site_claim, source role,
snapshot identity, literal statements and EvidenceRecord/excerpt envelopes; the
existing fact.evidence tuple carries their IDs. Confidence is conservatively 0.5.

The resolver order is:

1. Explicit authorized current_request (including separately confirmed facts).
2. Owned-site extracted observations.
3. Project/run context.
4. BrandProfile.
5. Conversation.

An explicit empty current value continues masking lower-priority context. Site
observations cannot overwrite it. The owned layer rejects product_truth,
existing_proof and values not marked site_claim. No shared PlanningInputKey or
AuthorizedContextFact shape is changed. Module instructions retain published-claim
attribution; existing evidence/gate semantics are unchanged.

`ConfirmedBusinessFact` is a separate typed attestation with snapshot_id,
statement_ids, confirmed_by and confirmation_reference. The caller must authenticate
the confirmer and collect actual explicit confirmation. Acquisition never constructs
this contract. `project_confirmation(snapshot, confirmation)` accepts only existing
OBSERVATION identities from that snapshot and returns a confirmed_business_fact
ContextEntry for **current_request.product_truth**. It does not mutate the site_claim
snapshot or independently verify the business. Caller-supplied existing explicit
product_truth remains supported without a snapshot. There is no confirmation UI.

Both strategy_builder_v1 and competitive_positioning_v1 reuse the projected
descriptive context. With product/audience/job recovered, missing product_truth
and/or relevant_alternative are returned together in NEEDS_INPUT. A site URL or
competitor URL does not supply the customer's actual alternative. No durable graph
starts while required POSITIONING inputs are missing. After explicit confirmation
and other required inputs, existing graph compilation, full-claim Quality Gates,
durability and worker execution proceed unchanged.

## Safe fetch, outcomes and limitations

The default explicit analyzer reuses UrlAnalyzer.analyze_url with
propagate_fetch_errors=True and no DB cache. A caller may inject an existing cached
UrlAnalyzer; its public_v1 cache policy, TTL and independent transactions are
unchanged. Cached content keeps unknown freshness: no new observed_at is fabricated
on acquisition. Evidence identities are code-generated and role-specific.

Existing safe_http applies public HTTP(S), no credentials, default ports, DNS/IP
validation at socket connection time, validated redirects, 1 MiB response cap,
25-second overall timeout, 10-second per-request timeout and four redirects. No
requests client, crawler, search, retries or alternate transport is added. The
extractor is never called on unsafe, failed, empty or over-budget source content.
Safe failures contain outcome codes, never raw credential/provider exception text.

Outcomes are ACQUIRED, UNSAFE_SOURCE, SOURCE_UNAVAILABLE, EMPTY_CONTENT,
CAPABILITY_UNAVAILABLE and INVALID_EXTRACTION. Only ACQUIRED has a snapshot.
safe_http policy rejections, including oversized responses, map to UNSAFE_SOURCE;
transport errors map to SOURCE_UNAVAILABLE. Caller contract misuse raises validation
errors. Unexpected programming errors propagate; cancellation is not swallowed.

V1 uses the bounded UrlAnalyzer text excerpt, metadata, headings and CTA text from
one HTML page, at most 16000 characters in total. Missing fields are unknown, not
proof that a feature/price is absent across the whole website. Existing text
extraction may omit short body lines, dynamic content and other pages. CTA text
does not verify the checkout path. No website effectiveness/SEO/UX audit, rendering,
autonomous discovery, competitor executor reuse, new module or persistent project.

## Verification

`tests/test_product_context.py` covers scenarios A–I, exact quote/schema rejection,
immutable round trip, explicit confirmation, all precedence layers, empty masks,
both workflow scenarios, role isolation and inaccessible-source recovery. Tests
exercise the real UrlAnalyzer/safe_http path with controlled HTML/redirect/stream
responses and private DNS answers, including numeric host forms, IPv4/IPv6,
credentials, malformed URLs, empty/oversized responses and timeouts. No live provider.

`tests/test_product_context_postgresql.py` checks both workflow scenarios against
disposable PostgreSQL: no run before confirmation, context/evidence persistence,
runtime recreation, module execution and full-claim acceptance through completion.
Existing safe URL, Copilot, Strategy Builder, executors, Registry, graph v1/v2,
Quality Gates, fixed MVP and standalone suites remain required regressions.

Manual internal verification: compose acquisition with an authorized test page and
controlled extractor; inspect snapshot citations and missing fields; attach it to
own URL + business goal; inspect grouped confirmation questions and absence of
durable work; add explicit confirmation and relevant alternative, then execute via
an explicitly configured Registry 1.2 Copilot/graph worker. Repeat with an explicit
competitor source and inspect separate source provenance. Public API and Telegram
continue using their unchanged production paths.
