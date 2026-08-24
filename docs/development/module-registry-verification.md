# Module Registry verification

This document records durable evidence for the initial `app/module_registry/v1.0.0.json` import.

## Release identity

- Green base: `17163e51fd360700a910e3224d4dc49c5d792d32`
- Registry version: `1.0.0`
- Canonical runtime resource: `app/module_registry/v1.0.0.json`
- Approved initial-import material: `docs/product/prompts/module-registry-production.md`
- Normalized JSON SHA-256: `25261485245902066cb6c59ef6cc612b18ab4cdabeebff6768e49816ba716918`
- Resource size: 40,323 Unicode characters; 47,588 UTF-8 bytes

Checksum normalization: UTF-8 JSON, lexicographically sorted object keys, preserved array order, and no insignificant whitespace.

## Import checklist

- [x] Exactly fifteen expected canonical IDs and one descriptor per ID.
- [x] Aliases and classified inputs match approved source material.
- [x] Outputs, supported tool flags, quality gates, and handoffs match.
- [x] Authority limitations match and self-handoffs are absent.
- [x] Every descriptor is `metadata_only` with no v1.0.0 binding.
- [x] Source version is `1.0.0`.
- [x] Normalized checksum is recorded.

The exact canonical ID set is `VIRTUAL_CMO`, `BUSINESS_DIAGNOSTICS`, `MARKET_ANALYSIS`, `COMPETITOR_ANALYSIS`, `POSITIONING`, `AD_AUDIT`, `CJM`, `CUSTDEV`, `CREATOR`, `COPY_EDITOR`, `LEAD_MAGNET`, `TREND_MONITORING`, `EXPERIMENTS`, `PROJECT_DEFENSE`, and `MENTOR`.

The canonical resource was compared field-by-field with `docs/product/prompts/module-registry-production.md` during the deterministic initial import. Direct one-module routing aliases were imported; compound and conditional aliases remain future Orchestrator routing rules rather than descriptor aliases. Lookup trims surrounding Unicode whitespace, case-folds, and collapses contiguous whitespace, ASCII hyphens, or underscores to one underscore. Tests cover normalized resolution, duplicate/empty aliases, canonical collisions, and cross-descriptor ambiguity.

## Evidence (complete only after execution)

| Check | Command/test | Result | Notes |
| --- | --- | --- | --- |
| Focused registry and compatibility tests | `.venv\Scripts\python.exe -m pytest -q tests\test_module_registry.py tests\test_agent_registry.py tests\test_task_router.py tests\test_task_pipeline_service.py tests\test_agents_router.py tests\test_agent_output_builder.py` | exit 0; 48 passed | No external calls |
| Expert Core tests | `.venv\Scripts\python.exe -m pytest -q tests\test_expert_core.py` | exit 0; 21 passed | Duplication guard is green on the repaired base |
| Full tests | `.venv\Scripts\python.exe -m pytest -q` | exit 0; 152 passed | 9 pre-existing deprecation warnings |
| Change validation | `openspec validate add-module-registry-foundation --strict` | exit 0; passed | Change is valid |
| All OpenSpec | `openspec validate --all --strict` | exit 0; 11 passed, 0 failed | Strict validation |
| Compile | `.venv\Scripts\python.exe -m compileall app bot` | exit 0; passed | Registry package and existing app/bot modules compiled |

## Package, Docker, and runtime evidence

`importlib.resources.files("app.module_registry")` loads the JSON independently of the current working directory. The immutable registry uses tuples, frozen sets, frozen dataclasses, and read-only mapping proxies; mutation tests confirm callers cannot alter nested or later-visible state. Canonical and alias lookup return the identical descriptor object.

The current deployment has no wheel/sdist packaging configuration. Docker uses `WORKDIR /app` and `COPY . .`, which deterministically places the tracked resource at `/app/app/module_registry/v1.0.0.json`. `docker info` exited 1 because the `docker_engine` daemon pipe was absent, so no image build was executed.

Registry construction and lookup perform zero LLM and QC calls. Version `1.0.0` has zero execution bindings. The existing `AgentRegistry` remains exactly `strategy`, `content`, `analytics`, `promo`, and `trends`; reviewed compatibility is partial only and therefore non-executable. No API, database/Alembic, Redis, worker, workflow, Telegram, routing, runner, pipeline, LLM, or QC behavior changed.

## Repaired Expert Core baseline

The Expert Core duplication guard was repaired in `sale-ready` before this recovery branch. On base `17163e51fd360700a910e3224d4dc49c5d792d32`, the required guard node passed (`1 passed`), the complete Expert Core file passed (`21 passed`), and the full suite passed (`152 passed`). This recovery changes no Expert Core runtime or test file.

## Compatibility and sign-off

Version `1.0.0` intentionally has zero bindings. Current compatibility is partial for `strategy`→`VIRTUAL_CMO`, `content`→`CREATOR`, `analytics`→`BUSINESS_DIAGNOSTICS`, `promo`→`AD_AUDIT`/`EXPERIMENTS`, and `trends`→`TREND_MONITORING`; all other pairings are none.

- Import reviewer: recovery PR review pending
- Compatibility reviewer: recovery PR review pending
- Runtime implementation commit: recorded in Git/PR after delivery
- Remaining deviations: Docker image was not built because the daemon was unavailable
