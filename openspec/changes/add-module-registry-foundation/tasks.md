# Tasks

## 1. Discovery

- [x] 1.1 Прочитать применимые `AGENTS.md`, архитектуру и текущие router/agent registry implementation points.
- [x] 1.2 Зафиксировать существующие canonical agent IDs, aliases и backward-compatibility constraints.
- [x] 1.3 Сопоставить production registry с реально существующими modules; отсутствующие modules оставить metadata-only и не реализовывать.

## 2. Domain contracts

- [x] 2.1 Добавить internal enums для canonical module identifiers, module types и tool capabilities.
- [x] 2.2 Добавить immutable module descriptor.
- [x] 2.3 Добавить activation и return contracts без изменения публичных DTO.

## 3. Registry

- [x] 3.1 Добавить canonical descriptors для production module IDs.
- [x] 3.2 Добавить alias resolution.
- [x] 3.3 Добавить fail-fast validation registry invariants.
- [x] 3.4 Предоставить read-only registry boundary для будущего routing без execution bindings, нового runner или изменения текущего routing behavior.

## 4. Tests

- [x] 4.1 Покрыть uniqueness IDs и aliases.
- [x] 4.2 Покрыть invalid handoffs и unsupported flags.
- [x] 4.3 Покрыть canonical alias resolution.
- [x] 4.4 Покрыть coverage существующих strategy/content/analytics/promo/trends agents.
- [x] 4.5 Подтвердить отсутствие изменений public API и database schema.

## 5. Documentation and verification

- [x] 5.1 Обновить verification documentation фактическим read-only integration boundary.
- [x] 5.2 Обновить task status по фактическим результатам green-base verification.
- [x] 5.3 Выполнить `python -m compileall app bot`.
- [x] 5.4 Выполнить `python -m pytest`.
- [x] 5.5 Выполнить `openspec validate add-module-registry-foundation --strict` и `openspec validate --all --strict`.
- [x] 5.6 Сообщить фактические результаты, limitations, API changes и migrations.
