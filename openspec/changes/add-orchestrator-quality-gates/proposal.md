# Change: Add orchestrator quality gates

## Why

Planning alone does not guarantee that downstream module results preserve evidence, assumptions, confidence, limitations and authority boundaries. The orchestrator needs deterministic gates for contract completeness and workflow decisions without pretending to verify arbitrary marketing truth.

## What changes

- Добавляется validation pipeline для normalized module returns.
- Добавляются PASS/PASS_WITH_LIMITATIONS/FAIL/BLOCKED rules.
- Добавляются evidence/confidence/limitation propagation rules.
- Добавляются contradiction records и deterministic conflict handling.
- Добавляются dynamic replanning и stop-condition decisions.
- Добавляются synthesis constraints and tests.

## Dependencies

- `add-expert-core-foundation`.
- `add-module-registry-foundation`.
- `add-marketing-orchestrator-foundation`.

## Out of scope

- Второй LLM QC call.
- Автоматическое доказательство factual truth, causality или strategic quality.
- Job retry/idempotency.
- Telegram delivery.
- Конкретные expert module implementations.

