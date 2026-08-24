# Tasks

## 1. Discovery

- [ ] 1.1 Прочитать применимые `AGENTS.md`, архитектуру и текущие router/agent registry implementation points.
- [ ] 1.2 Зафиксировать существующие canonical agent IDs, aliases и backward-compatibility constraints.
- [ ] 1.3 Сопоставить production registry с реально существующими modules; отсутствующие modules оставить metadata-only и не реализовывать.

## 2. Domain contracts

- [ ] 2.1 Добавить internal enums для module type, dependency type, module status и supported tool flags.
- [ ] 2.2 Добавить immutable module descriptor.
- [ ] 2.3 Добавить activation и return contracts без изменения публичных DTO.

## 3. Registry

- [ ] 3.1 Добавить canonical descriptors для production module IDs.
- [ ] 3.2 Добавить alias resolution.
- [ ] 3.3 Добавить fail-fast validation registry invariants.
- [ ] 3.4 Подключить registry к существующему routing boundary без создания нового runner.

## 4. Tests

- [ ] 4.1 Покрыть uniqueness IDs и aliases.
- [ ] 4.2 Покрыть invalid handoffs и unsupported flags.
- [ ] 4.3 Покрыть canonical alias resolution.
- [ ] 4.4 Покрыть coverage существующих strategy/content/analytics/promo/trends agents.
- [ ] 4.5 Подтвердить отсутствие изменений public API и database schema.

## 5. Documentation and verification

- [ ] 5.1 Обновить архитектурную документацию фактическим integration point.
- [ ] 5.2 Обновить roadmap status.
- [ ] 5.3 Выполнить `python -m compileall app bot`.
- [ ] 5.4 Выполнить `python -m pytest`.
- [ ] 5.5 Выполнить `openspec validate add-module-registry-foundation --strict`.
- [ ] 5.6 Сообщить фактические результаты, limitations, API changes и migrations.

