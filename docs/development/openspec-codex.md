# Development workflow

Use task -> implementation -> tests -> code review. Start a reviewable `codex/<task>` branch from current `sale-ready`; preserve local work and stash. Commit logical changes using conventional commit messages, then integrate verified work into `sale-ready`. `master` remains release history.

Read relevant code, architecture and existing contracts first. Record architecture, transaction ownership, reliability and API decisions alongside implementation. Existing `openspec/specs` and `openspec/changes` retain contracts and history; separate proposal/design/spec-review/apply or archival cycles are not required.

Run focused regressions during implementation. Before integration run `python -m pytest`, `python -m compileall app bot`, and `git diff --check`. Schema changes require a new migration from the actual head and upgrade/downgrade/re-upgrade on an explicitly disposable PostgreSQL database. Never downgrade a shared or production database. When editing OpenSpec itself, run `openspec validate --all --strict`.

Review correctness, ownership, concurrency, compatibility, failure handling and scope. Report actual command results, skips, migrations, branch/SHA, limitations and launch instructions. Do not bypass branch protection.

OpenSpec-generated skills are historical tooling; if explicitly needed, regenerate with the CLI instead of editing generated files.
