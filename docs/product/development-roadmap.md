# Development roadmap

## Completed foundations

- [x] OpenSpec and Codex bootstrap.
- [x] `add-marketing-workflow-persistence`.
- [x] Expert Core foundation.
- [x] Module Registry `1.0.0` with zero execution bindings.
- [x] Marketing Orchestrator deterministic planning foundation (`PLANNING_ONLY`).
- [x] Deterministic Orchestrator Quality Gates foundation (`PLANNING_ONLY`, no execution integration).

## Current

- [x] Apply `add-expert-core-foundation` (merged by PR #40).
- [x] Evaluate CORE behavior across strategy, content, analytics, promo and trends agents.
- [ ] Review the reconciled pre-implementation `add-durable-job-persistence` contract.

## Infrastructure and quality next

- [ ] Apply `add-durable-job-persistence` after its specification is accepted.
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
- Durable Job persistence is PostgreSQL-only and uses `pending/version=0 -> running/version=1 -> succeeded|failed/version=2`; a mandatory observed version under the row lock permits only one successful transition per observed version, and dirty target owner/immutable history is rejected before SQL. Publication, claiming, retries, idempotency, cancellation and delivery remain later changes.
- Durable Jobs are operational run/user aggregate children or trusted-internal system records; owner deletion cascades, public anonymous creation and user/system listing are absent, and retained audit history requires a separate change.
- `master` receives changes only after integration through `sale-ready`.
