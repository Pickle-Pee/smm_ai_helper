# Prompt source map

## Purpose

This document separates product source material, runtime sources and design history so duplicate routing components and conflicting canonical sources are not created.

## Source precedence

| Domain | Normative contract/runtime source | Supporting source/history | Decision |
| --- | --- | --- | --- |
| Shared reasoning policy | versioned Expert Core runtime resource | `docs/product/prompts/expert-core-production.md`, early general prompt | one Expert Core runtime source |
| Marketing Orchestrator foundation | `docs/product/marketing-orchestrator.md` product contract plus active OpenSpec/typed rules | `docs/product/prompts/orchestrator-production.md`, early Orchestrator/dispatcher documents | deterministic foundation loads no prompt; no separate dispatcher |
| Module metadata/routing | `app/module_registry/v1.0.0.json` | `docs/product/prompts/module-registry-production.md`, early registry | runtime Registry resource is canonical metadata |

## Reconciliation decisions

Early general prompt concerns are split among Expert Core, Orchestrator, Module Registry and specialized modules. Early dispatcher responsibilities overlap Orchestrator planning; a separate dispatcher would duplicate routing and is not created.

`docs/product/prompts/orchestrator-production.md` is approved version-controlled product source for a broader future lifecycle, not a canonical runtime prompt for `add-marketing-orchestrator-foundation`. The foundation makes no LLM call and creates no `app/prompts/orchestrator`; typed code and deterministic OpenSpec rules own runtime planning behavior.

A future model-driven planner must define one versioned runtime prompt in a separate OpenSpec change with evals, call-budget/token and latency review. Until then, no Orchestrator file is called a canonical runtime prompt.

## Editing rule

Moving an approved product rule into runtime requires product rationale, an OpenSpec behavior change, one versioned runtime source, tests/evals, conflict review and call-budget review when a model is involved. Legacy DOCX material remains design history rather than runtime source.
