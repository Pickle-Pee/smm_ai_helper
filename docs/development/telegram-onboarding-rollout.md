# Telegram onboarding rollout

Deploy only after review, green PostgreSQL and container CI, and the separate production authorization. Confirm Alembic has one head at the combined release tree. With B4 integrated first, revision 0019 must follow 0018. Bring the schema forward with the feature disabled before changing configuration.

## Cohort and rollback

- Default: TELEGRAM_ONBOARDING_ENABLED=false in both bot and backend.
- Closed cohort: use TELEGRAM_ONBOARDING_ENABLED=true with TELEGRAM_ONBOARDING_COHORT set to the same nonempty JSON array of numeric Telegram user IDs in both processes. Keep this array in trusted runtime configuration. An empty array with the flag enabled applies to all authenticated Telegram users.
- First verify a fresh actor and existing actors with complete and partial profiles. Verify retry, restart, saved results, profile editing, and delivery. Confirm off-cohort behavior with an additional actor.
- Roll back by setting the flag to false in both processes. Keep revision 0019 and the persisted data in place. Flags control admission and UX only.

## Measurement

Aggregate events from the telegram_onboarding logger. Its event payload contains only fixed event and step enums. Do not enrich these events with user identifiers, messages, names or profiles.

| Metric | Calculation |
|---|---|
| Prompt and resume traffic | Count resume by step. Repeated views count separately. |
| Progress | Count committed answer_saved by step and transitions to ready. Existing profiles may skip several steps. |
| Prevented generation | blocked / (allowed + blocked) for scoped admission checks. Report unavailable separately. These are request attempts, not unique users. |
| Input and output tokens | Compare mean and p95 from existing provider usage telemetry on matched operation kinds, model versions and use cases. Report usage coverage. Aggregate retries consistently. |
| Answer quality | Use the same blind rubric for both cohorts. Track actionability, specificity to supplied business context and unsupported claims. Record aggregate ratings and acceptance rates without exporting user content into metrics. |

Use paired offline fixtures first. During a separately approved trial, report sample sizes, baseline and cohort windows and per-operation mix alongside deltas. No live token or quality claim follows from the rollout tests alone.
