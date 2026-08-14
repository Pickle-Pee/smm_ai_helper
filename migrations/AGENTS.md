# Migration instructions

These rules extend the repository-level `AGENTS.md` for Alembic work under `migrations/`.

- Never modify an already merged migration to represent a new schema change.
- Create a new revision from the current migration head.
- Keep model constraints, foreign keys, indexes, nullability, and migration operations aligned.
- Consider both `upgrade()` and `downgrade()` behavior.
- Avoid destructive data changes unless the active OpenSpec change explicitly documents migration/rollback behavior.
- Validate migrations against PostgreSQL when the environment permits it.
- Run `alembic upgrade head` for schema-changing work and report whether it actually passed.