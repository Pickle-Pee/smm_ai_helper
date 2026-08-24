# Module Registry product contract

## Responsibility and registry boundary

`ModuleRegistry` is a read-only product/domain catalog of applicability, inputs, outputs, capabilities, quality gates, authority limits, and handoffs. It does not instantiate modules, select execution paths, or orchestrate workflows.

The existing `AgentRegistry` separately maps executable IDs `strategy`, `content`, `analytics`, `promo`, and `trends` to classes. `ModuleRegistry` does not replace it, and product aliases are not agent aliases.

## Canonical runtime source

The single canonical runtime source is `app/module_registry/v1.0.0.json`, version `1.0.0`. Descriptor content must not be duplicated in Python constants, Markdown, or another runtime resource.

- `docs/product/prompts/module-registry-production.md` is approved initial-import material, not runtime data.
- Archival DOCX documents are source history only.
- This document defines boundaries, not descriptor copies.
- Python provides immutable types, loading, validation, and lookup only.
- `docs/development/module-registry-verification.md` records evidence only.

Docker `COPY . .` makes the resource available at `/app/app/module_registry/v1.0.0.json`; the current deployment does not build/install a wheel or sdist.

## Canonical IDs and descriptor contract

Version `1.0.0` contains exactly: `VIRTUAL_CMO`, `BUSINESS_DIAGNOSTICS`, `MARKET_ANALYSIS`, `COMPETITOR_ANALYSIS`, `POSITIONING`, `AD_AUDIT`, `CJM`, `CUSTDEV`, `CREATOR`, `COPY_EDITOR`, `LEAD_MAGNET`, `TREND_MONITORING`, `EXPERIMENTS`, `PROJECT_DEFENSE`, and `MENTOR`.

Each immutable descriptor declares canonical ID, module types, purpose/applicability, classified inputs, outputs, supported capabilities, quality gates, aliases, handoffs, authority limitations, availability, and optional binding. Availability (`metadata_only`/`execution_bound`) is separate from result status (`PASS`, `PASS_WITH_LIMITATIONS`, `FAIL`, `BLOCKED`). Activation/return contracts are internal and do not replace public DTOs, `AgentInput`, `AgentOutput`, presenters, agent dictionaries, or task results.

## Execution binding policy

A binding may reference an existing `AgentRegistry` ID only for `exact` compatibility. It is metadata, not execution. `partial` and `none` remain metadata-only. Version `1.0.0` has no bindings.

| Product module | Possible agent | Compatibility | Binding | Evidence summary |
| --- | --- | --- | --- | --- |
| `VIRTUAL_CMO` | `strategy` | partial | no | SMM strategy overlaps, but economics, resource trade-offs and full module outputs are absent. |
| `CREATOR` | `content` | partial | no | Content planning/posts overlap, but the broader creative-system contract is absent. |
| `BUSINESS_DIAGNOSTICS` | `analytics` | partial | no | Metrics/diagnosis overlap, but the business-economics contract is absent. |
| `AD_AUDIT` / `EXPERIMENTS` | `promo` | partial | no | Campaign/testing overlaps, but neither full module contract is implemented. |
| `TREND_MONITORING` | `trends` | partial | no | Trend ideation overlaps, but current evidence/provenance and lifecycle requirements are absent. |

All other product-module/current-agent pairings are `none`.

## Alias and validation invariants

Alias lookup trims Unicode whitespace, case-folds, and converts runs of whitespace/hyphens/underscores to one underscore. Canonical IDs and aliases share one namespace. Empty values, collisions, and ambiguity fail validation; lookup returns the canonical descriptor only.

Loading also fails for duplicate/missing/unexpected IDs, invalid counts/fields/enums, unsupported flags, invalid/self handoffs, invalid binding state/targets, wrong version, or mutation attempts. Supported v1.0.0 capabilities are `web_access`, `file_analysis`, `site_fetch`, `image_generation`, and `code_generation`.

## Scope boundary

This foundation does not change `TaskRouter`, `AgentRunner`, `TaskPipelineService`, public APIs, persistence, migrations, Telegram behavior, LLM/QC calls, or execution. Future Marketing Orchestrator work may consume the read-only registry.
