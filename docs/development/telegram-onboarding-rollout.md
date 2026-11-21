# Telegram onboarding rollout

Deploy only after review, green PostgreSQL and container CI, and the separate production authorization. Confirm Alembic has one head at the combined release tree. With B4 integrated first, revision 0019 must follow 0018. Bring the schema forward with the feature disabled before changing configuration.

## Cohort and rollback

- Default: TELEGRAM_ONBOARDING_ENABLED=false in both bot and backend.
- Closed cohort: use TELEGRAM_ONBOARDING_ENABLED=true with TELEGRAM_ONBOARDING_COHORT set to the same nonempty JSON array of numeric Telegram user IDs in both processes. Keep this array in trusted runtime configuration. An empty or omitted cohort leaves onboarding disabled for everyone.
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

## Release gate

Record the candidate SHA, image digest, observed production schema revision, staged migration evidence, and the release owner before requesting permission. Obtain explicit approval for the deployment and migration window, then apply the schema with the feature disabled. Retain a backup and verify the bot, backend, worker, delivery and Web API before adding any account to the cohort.

Use a dedicated Telegram test account in the closed cohort and a second account outside the cohort. On the fresh in-cohort account, send /start, set a preferred name, stop after the product answer, then restart the bot and resume. Simulate a save failure in staging and retry the original answer. Check that the final committed answer opens the menu. Before completion, exercise a direct request and a legacy callback and verify no new job or provider traffic. After completion use the fake provider for an accepted request, read its result and verify delivery. Reopen /start, edit the preferred name, repeat with a partial existing profile, and confirm history remains visible.

Compare the outside account's entry points and profile to baseline. Check existing Web API and B4 onboarding using test users. Monitor aggregate step completion, allowed, blocked and unavailable admission, and delivery failures. Stop the rollout and disable the flag in both processes if ownership, profile persistence, admission, delivery or Web API regresses. Expand the cohort only after the owner signs off on the closed trial. Any trial involving real paid generation requires separate explicit authorization.
