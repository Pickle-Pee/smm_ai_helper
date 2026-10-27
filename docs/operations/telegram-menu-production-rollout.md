# Telegram menu production rollout — PREPARING

Status: **PREPARING / NOT_DEPLOYED**. Preparation is in progress. This report does
not establish that the menu is running in production or authorize cutover.

The [public summary](telegram-menu-production-rollout.manifest.json) records gate
states only. Detailed execution evidence, image identities, configuration,
infrastructure inventory and backup records belong in protected operator storage.

## Release scope

The release combines menu [PR #131](https://github.com/Pickle-Pee/smm_ai_helper/pull/131),
required dependency [PR #129](https://github.com/Pickle-Pee/smm_ai_helper/pull/129),
and the minimal Alembic driver fix in
[PR #133](https://github.com/Pickle-Pee/smm_ai_helper/pull/133).
The assembled candidate is tracked by
[PR #134](https://github.com/Pickle-Pee/smm_ai_helper/pull/134).
PR #130 and its output-budget experiment are excluded.

Alembic explicitly selects the installed synchronous psycopg2 driver; application
runtime retains asyncpg. Production connection settings and OpenAI configuration
have not been changed. The menu retains its documented bounded dialogue context.

## Confirmed by execution

- A consistent production database backup was created using an exported snapshot
  and stored with restricted operator access outside the public repository.
- Its checksum was verified. Restoration into a separate, network-isolated
  disposable PostgreSQL instance succeeded; checked table counts and foreign-key
  relationships matched the same exported source snapshot.
- Previous application images and configuration were archived with restricted
  operator access. Archive availability does not prove application rollback
  compatibility; a rehearsal remains required.
- No production application replacement, schema migration, worker admission
  change or application-data write was performed by this rollout.

Backup preparation writes protected operator files. It does not mean that the
production host was entirely untouched. Production may continue serving unrelated
user traffic; this report does not claim global inactivity.

## Verified by observation

- Production remained on the previously deployed source baseline.
- Application and data services were running; observed health checks passed.
- Dependency and menu source identities matched the intended chain.
- Independent source review found no changes to existing OpenAI model/reasoning
  configuration, generation limits or graph scheduling. Graph changes add
  deterministic history metadata; the dependency adds the intended contextual
  Mentor and recovery behavior.

These are preparation snapshots. They do not replace fresh live checks before
cutover or establish complete writer and accepted-handler inventory.

## Not verified

| Required gate | Current state |
| --- | --- |
| Complete CI for the exact driver-fix commit | Pending; dependency compatibility issue under investigation |
| Complete CI for the exact assembled candidate | Pending |
| Immutable release build and runtime source attestation | Not verified |
| Isolated staging menu/context/security acceptance | Not verified |
| Migration duration, locks and schema parity on restored data | Not verified |
| Previous application images on the additive schema | Not verified |
| Complete writer inventory and effective ingress barrier | Not verified |
| Dedicated least-privilege access and live epoch-fenced drain | Not verified |
| Production menu/history using a controlled operator account | Not run |
| Paid-provider continuation and live model quality | Not run; no paid test authorized |

Historical CI and empty queue snapshots do not pass live deployment gates. No
second Telegram poller, message to other users, paid generation, destructive
downgrade, volume deletion or forced claim cleanup is part of this preparation.

## Next required actions

1. Resolve dependency compatibility and complete both required CI jobs for the
   exact driver-fix and assembled candidate commits.
2. Build and attest immutable artifacts; complete isolated staging acceptance,
   migration rehearsal and application rollback on the expanded schema.
3. Account for every writer and accepted synchronous handler, close all applicable
   ingress, and pass the dedicated live worker-drain gate.
4. Only after all mandatory gates pass, perform the controlled additive migration,
   application cutover and safe production acceptance.

If a mandatory gate cannot be completed, the final report must identify that gate,
the executed remedies, the remaining technical limitation, its required remedy and
why proceeding would be unsafe. This in-progress report declares neither final
NO_GO nor successful deployment.

## Publication boundary

An earlier version exposed unnecessary operational details. This revision replaces
those details with a public status summary. **Earlier details remain accessible in
existing Git commits**; no history rewrite or removal is claimed. No credentials
or user payloads were found in the reviewed prior report. That limited review is
not a claim about the entire repository history.
