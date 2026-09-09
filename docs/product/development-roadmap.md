# Development roadmap

Status reflects the executable fixed MVP and its tests, not production deployment. Historical OpenSpec names identify design work; an unarchived proposal is not evidence that its runtime is still missing.

## Completed foundations

- [x] OpenSpec/Codex bootstrap; current workflow is task -> implementation -> tests -> code review.
- [x] MarketingRun / MarketingArtifact persistence.
- [x] Expert Core composition and evaluations across standalone agents.
- [x] Module Registry `1.0.0`: metadata-only, zero execution bindings.
- [x] Generic Marketing Orchestrator deterministic planner: always `PLANNING_ONLY`.
- [x] Pure deterministic Quality Gates evaluator and immutable eligibility manifest. Registry-derived readiness stays `PLANNING_ONLY`.
- [x] Durable Job model/service/migration `20260825_0004`, with caller-owned transactions and closed lifecycle `pending -> running -> succeeded|failed`.

## Completed fixed MVP vertical

| Earlier roadmap intent | Implemented fixed scope | Broader work still future |
| --- | --- | --- |
| `add-redis-worker-foundation` | Redis job-ID wakeups, PostgreSQL due scan, fixed workflow workers | General-purpose queue framework / arbitrary task dispatch |
| `add-competitor-analysis`, `add-competitor-analysis-workflow` | One public HTML page + BrandProfile/input snapshot -> saved analysis/evidence | Broad crawling, gated social sources, full market research |
| `add-creative-package`, `add-commercial-creative-workflow` | Saved analysis -> commercial angle, offer, headline/CTA, generated banner and Reels/Shorts scene script | Generic creative system, final video generation/editing |
| `add-mentor-insight` | Explicit user opt-in -> explanation of saved analysis/creative decisions | Generalized teaching, project defense and interactive hypothesis coaching |
| `integrate-expert-core-with-marketing-workflows` | Expert Core composition in three explicit executors | Arbitrary Registry module implementations/bindings |
| Quality Gates execution integration | Explicit `app/workflows/quality.py` adapter before artifact persistence; typed evidence/claims/lineage | Generic agent adapters, semantic truth verification, autonomous replanning/synthesis |
| `add-telegram-marketing-workflow` | Private-chat commands, owner-scoped API/media, saved results and continuation buttons | Other channels and broader interaction modes |
| `add-job-retries-and-idempotency` | JobExecution attempts/leases/fencing, three bounded claims, request/step reuse, PostgreSQL recovery | General retry/cancellation framework, exactly-once provider effects |
| `add-telegram-delivery-worker` | Independent durable delivery claims, ordered parts, bounded retries and acknowledgements | Exactly-once Telegram delivery |
| `add-integration-release-gates` | PostgreSQL migrations/concurrency/crash tests, provider doubles, Redis CI and container recreation smoke | Live commercial acceptance, operational production rollout |

Artifacts, Job outcome, run transition and Telegram delivery parts commit together. Retry attempts do not rewind Job's foundation lifecycle. JobExecution and delivery own separate recovery state; Redis is not canonical business storage. Details and exact limits: [fixed MVP contract](../development/marketing-mvp.md).

## Standalone reliability

- [x] Atomic Task history + canonical session response and later replay.
- [x] PostgreSQL continuation claim before routing/model/QC/image calls; concurrent final answers converge without duplicate execution in a valid attempt.
- [x] Bounded execution/wait, owner fencing, failure release and expired-claim recovery without Redis or long provider-spanning transactions.

See [standalone task contract](../task_pipeline.md). Recovery after ambiguous external effects may repeat provider calls; this is not an exactly-once provider guarantee.

## Future product and generalized runtime

- [ ] Executable generic Marketing Orchestrator and arbitrary execution of all 15 Registry modules.
- [ ] Model-driven planning, autonomous replanning and generic user-facing synthesis.
- [ ] Broader source coverage, campaign execution and CRM integrations.
- [ ] Final video generation/editing, generalized mentoring and customer-research workflows.
- [ ] Live acceptance with real providers/Telegram, cost/usage controls and production deployment.

## Development rules

- Use a dedicated `codex/<task>` branch from current `sale-ready`; integrate only after implementation, tests and review. `master` remains release history.
- Preserve existing OpenSpec contracts as reference/history; separate approval/apply/archive cycles are optional.
- Keep the fixed workflow separate from standalone TaskPipelineService and the generic planning boundary. Fixed execution never implies a Registry execution binding.
- Model-driven planning needs a reviewed design, one versioned runtime prompt, evals and call-budget/latency review.
- Job remains an operational run/user aggregate child or trusted internal system record. Owner deletion cascades; public anonymous creation, direct user/system listing and retained audit history are not added by the fixed MVP.
