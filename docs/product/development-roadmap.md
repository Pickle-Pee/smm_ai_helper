# Development roadmap

## Completed foundations

- [x] OpenSpec and Codex bootstrap.
- [x] `add-marketing-workflow-persistence`.
- [x] Expert Core foundation.
- [x] Module Registry `1.0.0` with zero execution bindings.
- [x] Marketing Orchestrator deterministic planning foundation (`PLANNING_ONLY`).

## Current

- [x] Apply `add-expert-core-foundation` (merged by PR #40).
- [x] Evaluate CORE behavior across strategy, content, analytics, promo and trends agents.
- [ ] Reconcile and review `add-orchestrator-quality-gates` before runtime implementation.

## Infrastructure and quality next

- [ ] Implement the deterministic `add-orchestrator-quality-gates` foundation after the reconciled specification is accepted.
- [ ] `add-durable-job-persistence`.
- [ ] `add-redis-worker-foundation`.

## Product vertical

- [ ] `add-competitor-analysis`.
- [ ] `add-competitor-analysis-workflow`.
- [ ] `add-creative-package`.
- [ ] `add-commercial-creative-workflow`.
- [ ] `add-mentor-insight`.
- [ ] `integrate-expert-core-with-marketing-workflows`.
- [ ] `add-telegram-marketing-workflow`.

## Reliability and release

- [ ] `add-job-retries-and-idempotency`.
- [ ] `add-telegram-delivery-worker`.
- [ ] `add-integration-release-gates`.

## Sequencing rules

- One change uses one `agent/<change-name>` branch from current `sale-ready`.
- OpenSpec is reviewed before runtime implementation.
- Runtime implementation is a separate apply step; the roadmap is not an implementation spec.
- The Orchestrator foundation is planning-only: structured interpretation, exact deterministic scenarios and validated graphs.
- Execution waits for durable Job/workers and is owned by `MarketingWorkflowService`.
- Model-driven planning, an executable Orchestrator prompt, runtime QC/replanning and synthesis require later OpenSpec changes.
- Quality Gates are a pure normalized-result foundation; agent adapters, revised-plan generation, workflow execution and user-facing synthesis remain later changes.
- `master` receives changes only after integration through `sale-ready`.
