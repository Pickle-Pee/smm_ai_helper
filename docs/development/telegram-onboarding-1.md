# Telegram onboarding 1.0

Audited backend master 569abe1c. The private Telegram router in bot/project_navigation.py owns menu navigation. bot/main.py registers navigation and active project routing ahead of ordinary chat. The database owns progress. Telegram FSM may select a renderer, but cannot grant generation.

| Entry point | Current destination | Contract and check |
|---|---|---|
| /start, /menu, home callback | show_menu | Resolve persisted step. Reopening any of these restores the same step. |
| /new and new from history (pn:n) | POST /projects/context | Navigation only. Offer onboarding when needed. Creating a new binding or draft conveys no generation authorization. |
| /brand, pn:profile, three questions | PUT /workflows/profile | Available before readiness. Save each missing field through the existing profile workflow. Confirm only after commit. |
| Ordinary text, action callbacks, clarification | POST /chat/message or /copilot/execute | Guard both before admission and provider dispatch. |
| Active project text, saved discussion | POST /projects/context/messages | Guard new turns, including routes through mentor or chat. GET discussion stays available. |
| /analyze, /context, mvp callbacks | POST /workflows, PATCH /workflows/{run_id}/context, POST /workflows/{run_id}/continue | Guard anything that can enqueue. Incomplete profile remains editable via PUT /workflows/profile. |
| Agent selection, task answers, inline detail actions | POST /tasks/start, /tasks/answer, /agents/{agent_type}/run | Guard all three, including final answers and older callbacks. Preserve existing owner bindings. |
| Image wizard or direct legacy image generation | POST /images/generate | Guard before image orchestration. Owned image downloads remain available. |
| task_repeat callback | POST /agents/{agent_type}/run | Treat a repeat as new generation. |
| Mentor callbacks and questions | POST /copilot/runs/{run_id}/mentor and /mentor/questions | Guard operations that may generate, including cache misses. GET explanations and prior Q&A stay available. |
| /history, /projects, /active, /runs, /status, /result, /copilot_runs, /copilot_result, /case_history | Existing GETs and project selection | Preserve existing access and owner checks. |
| Feedback, /redeliver, automatic delivery, durable execution recovery | Feedback and delivery write paths, worker processing | These do not admit a new paid request. Keep outside the HTTP admission gate. |
| Direct backend calls to the above mutation routes | Bot bearer and authenticated actor headers | Apply the same admission check independently of the Telegram UI. Body identities must still pass existing owner checks. Web session routes remain separate. |

## Persisted contract

- Resolve the existing verified Telegram identity to users.id after bot authentication. A missing identity is incomplete. First-run writes may create a Telegram user through the existing user service and database identity trigger. Never grant access based on a body-provided owner.
- Keep preferred_display_name on the user record, separate from first_name and brand context. Name is editable. It guides the welcome sequence, while server admission is based on brand readiness.
- Reuse the user's BrandProfile. Require non-blank product_description and audience plus at least one non-blank string in the goals array. Workflow overrides, draft text, old project snapshots and FSM do not contribute. No derived completed flag. Existing ready profiles qualify without a backfill.
- Project the next missing step from committed state in order name, product, audience, goal. Each successful answer commits independently. Use a server-side serialization point for conditional answer writes, and bind each Telegram answer to the prompt it answers so duplicate or delayed updates cannot advance another step. Keep the current reply retryable if persistence fails.
- Admission reads committed profile state immediately before handing off to an operation. During first save an uncommitted profile cannot qualify. A request admitted while ready may finish after a later profile edit. Middleware, polling and workers must avoid holding a database transaction across provider work.
- Use a default-off rollout with a configured Telegram test cohort. Restrict configuration to trusted settings. Missing readiness returns 409 onboarding_required. Database errors fail closed with 503 and do not include profile content.
- Reserve 0019 for a preferred name column. B4 owns 0018. If 0019 is developed on current master before B4 lands, reparent the unmerged migration to 0018 when integrating after B4 and re-run checks on the combined head. Keep CI and PRs independent of B4 during development.

## Verification

Use dependency spies and the fake provider to assert zero provider POSTs and zero new paid jobs on each blocked mutation. Use PostgreSQL for actor/owner binding, existing versus partial profiles and concurrent uncommitted profile saves. Use PostgreSQL and Redis for repeat updates, restart and recovery. Include allowed read-only routes, accepted delivery, a ready profile and flag-off behavior. Measure aggregate step counts and admission decisions without user content. Production rollout and token/quality comparisons require separate approval and real observations.
