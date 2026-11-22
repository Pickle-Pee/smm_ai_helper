# Telegram onboarding rollout

Build the bot, backend and worker from the same revision. Take a verified database backup and retain the prior image and Compose configuration before replacing the application. Apply the additive Alembic revision 20261122_0020 before starting the new image.

## Modes and rollback

| Settings in bot and backend | Behavior |
|---|---|
| TELEGRAM_ONBOARDING_ENABLED=false | Onboarding admission and Telegram prompts are disabled. This is the default. |
| TELEGRAM_ONBOARDING_ENABLED=true and TELEGRAM_ONBOARDING_MODE=cohort | Only numeric Telegram IDs in TELEGRAM_ONBOARDING_COHORT participate. Omitted and empty cohorts admit nobody. |
| TELEGRAM_ONBOARDING_ENABLED=true and TELEGRAM_ONBOARDING_MODE=all-users | All authenticated Telegram actors participate. |

Set these values through the shared runtime configuration. The mode defaults to cohort. Invalid modes and invalid cohort IDs fail configuration validation. Before polling, the bot compares its effective mode and cohort signature with the authenticated backend endpoint.

To disable onboarding immediately, set TELEGRAM_ONBOARDING_ENABLED=false for both processes and recreate them together. Preserve persisted names, profiles and messages. The previous application image is compatible with the additive schema.

New Telegram replies are tied to their current question or the prompt that preceded their message. The backend records the highest accepted Telegram message ID with the committed profile change so redelivery after restart cannot become a new generation. Profile readiness and name remain durable, and /start restores the first missing step.

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

Verify the candidate SHA, image digest and schema revision. Run PostgreSQL and container CI and validate the 12 protected Telegram routes with synthetic actors and a fake provider. A blocked request returns 409 onboarding_required without accepting generation or creating jobs. Check history and saved results by using their read routes. Run B4 and Web Auth regression tests.

Use a dedicated Telegram test account for /start, plain-text answers, restart after a partial profile, first generation from stored brand input, saved-result delivery and editing. Test retries with the fake provider and use synthetic brand data for the limited live model check. Keep existing history and profiles intact. Use separate authenticated synthetic actors to verify isolation when only one Telegram account is available. Record separately which steps ran through the real Telegram transport.
