# OpenSpec + Codex development workflow

## Purpose

OpenSpec defines and reviews intended behavior before code is implemented. `AGENTS.md` defines persistent repository rules for Codex. Git isolates and reviews each change.

## Prerequisites

- Git
- Python 3.11
- Node.js 20.19 or newer
- Codex
- OpenSpec CLI

Install or update OpenSpec:

```bash
npm install -g @fission-ai/openspec@latest
openspec --version
```

## Configure Codex for this repository

From the repository root, on a developer machine:

```bash
openspec init --tools codex --profile core
```

For an already initialized repository or after upgrading OpenSpec:

```bash
openspec update
```

OpenSpec generates Codex workflow skills under `.codex/skills/openspec-*`. Treat those files as generated output: regenerate them with OpenSpec rather than editing them manually. Restart Codex after generating/updating skills so it reloads project instructions and skills.

The core OpenSpec profile provides the explore, propose, apply, sync, and archive workflows.

## Repository concepts

- `AGENTS.md`: repository-wide coding-agent rules.
- nested `AGENTS.md`: additional rules for backend, Telegram, tests, and migrations.
- `openspec/config.yaml`: project context and artifact-specific planning rules.
- `openspec/specs/`: current observable behavior (source of truth).
- `openspec/changes/<change>/`: proposed change artifacts.
- `docs/product/`: product direction and scope; not automatically current system behavior.
- `ARCHITECTURE.md`: current architecture plus explicitly marked planned architecture.

## Branch model

`master` is release history and must not be used for direct feature implementation.

`sale-ready` is the integration branch.

Each OpenSpec change uses a task branch, preferably:

```text
agent/<change-name>
```

Example:

```text
sale-ready
  └── agent/add-marketing-workflow-persistence
```

One OpenSpec change should normally produce one reviewable PR into `sale-ready`. Merge `sale-ready` into `master` only after regression/release validation.

## Workflow for a feature or architectural change

1. Update local integration branch.
2. Create a task branch.
3. Explore the change with Codex/OpenSpec when the problem is not fully shaped.
4. Create `openspec/changes/<change>/` and generate/review:
   - `proposal.md`;
   - delta `specs/.../spec.md`;
   - `design.md`;
   - `tasks.md`.
5. Review the artifacts before implementation.
6. Apply the tasks with Codex.
7. Run the required tests/checks.
8. Review the Git diff for unrelated changes.
9. Verify the change against its spec scenarios.
10. Archive/sync the OpenSpec change after acceptance.
11. Commit and open a PR into `sale-ready`.

## Small fixes

A typo, documentation clarification, test-only addition, or bug fix that only restores already-specified behavior may not require a new OpenSpec proposal. If a fix changes public behavior, architecture, persistence, reliability semantics, or a user-visible contract, create a change.

## Useful OpenSpec CLI checks

```bash
openspec list
openspec list --specs
openspec validate --all --strict
openspec status --change <change-name>
```

## Definition of done

A change is not complete until:

- implementation matches approved OpenSpec artifacts;
- tests were added/updated for changed behavior;
- relevant verification commands actually passed or blockers are documented;
- migrations were tested when present;
- no unrelated code was included;
- Codex reports files changed, commands run, checks passed, and remaining limitations;
- OpenSpec specs are synchronized/archived when the implementation is accepted.