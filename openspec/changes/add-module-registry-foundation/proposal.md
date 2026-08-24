# Change: Add module registry foundation

## Why

Система имеет production-описание пятнадцати экспертных модулей, aliases, activation/return contracts и routing precedence, но эти сведения должны стать единым version-controlled runtime contract. Без canonical registry routing будет зависеть от копий prompt text, а module IDs и input/output expectations начнут расходиться.

## What changes

- Добавляется canonical, versioned module registry.
- Добавляются typed module descriptors и enums для module type, dependency type, tool flags и module status.
- Добавляются canonical module IDs и alias resolution.
- Добавляются activation и return contracts на уровне internal domain models.
- Существующий routing получает registry через один read-only boundary.
- Добавляются validation и deterministic tests registry invariants.

## Impact

- Публичные API не меняются.
- Database schema и Alembic migrations не меняются.
- `TaskPipelineService` остаётся single-task pipeline.
- Registry не исполняет модули и не хранит business state.
- Существующие standalone agents продолжают работать через текущий execution path.

## Out of scope

- Multi-module workflow execution.
- Redis, Jobs и workers.
- Реализация отсутствующих expert modules.
- LLM-based routing или QC.
- Изменение пользовательских response formats.

