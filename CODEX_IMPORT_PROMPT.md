# Prompt for Codex Desktop

```text
Integrate the provided AI Marketing System documentation package into this repository.

Before changing files:
1. Read all applicable AGENTS.md files.
2. Read ARCHITECTURE.md and docs/development/openspec-codex.md.
3. Inspect existing docs/product and openspec/changes directories.
4. Inspect git status and preserve unrelated changes.

Copy the package files into the repository using their relative paths, but:
- do not overwrite `openspec/changes/add-expert-core-foundation`;
- preserve any newer repository-specific decisions;
- report path or content conflicts before resolving them;
- do not implement runtime code;
- do not modify existing Alembic migrations;
- do not change public APIs;
- do not create a Dispatcher runtime component separate from Orchestrator;
- keep TaskPipelineService a single-task pipeline;
- keep PostgreSQL as durable source of truth and Redis as transport/coordination only.

After integration:
1. Check internal Markdown links.
2. Run `openspec validate --all --strict`.
3. Report every added or changed file.
4. Report validation output and any conflicts.
5. STOP. Do not apply any OpenSpec change yet.
```
