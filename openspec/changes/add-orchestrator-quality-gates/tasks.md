# Tasks

## 1. Discovery

- [ ] 1.1 Найти существующие `QCService`, result models и persistence boundaries.
- [ ] 1.2 Определить, какие проверки уже существуют и должны быть переиспользованы.
- [ ] 1.3 Зафиксировать transaction ownership для accepted artifacts/state updates без изменения persistence semantics вне scope.

## 2. Gate contracts

- [ ] 2.1 Добавить gate result и failure reason types.
- [ ] 2.2 Реализовать status transition rules.
- [ ] 2.3 Реализовать structural validation normalized module returns.
- [ ] 2.4 Реализовать evidence/confidence/limitations propagation.
- [ ] 2.5 Реализовать registered handoff validation.

## 3. Contradictions and replanning

- [ ] 3.1 Добавить contradiction record.
- [ ] 3.2 Реализовать deterministic comparison fields: object, segment, period, metric definition, source and freshness.
- [ ] 3.3 Добавить replanning decision contract.
- [ ] 3.4 Добавить stop-condition evaluation.
- [ ] 3.5 Сохранять prior plan/findings immutable либо по существующей versioning convention.

## 4. Synthesis constraints

- [ ] 4.1 Синтезировать только accepted module results и explicit limitations.
- [ ] 4.2 Не выдавать raw module dump.
- [ ] 4.3 Не раскрывать hidden chain-of-thought.
- [ ] 4.4 Адаптировать simple/complex response format без одного жёсткого шаблона.

## 5. Tests

- [ ] 5.1 PASS/PASS_WITH_LIMITATIONS/FAIL/BLOCKED transitions.
- [ ] 5.2 Confidence не повышается без нового evidence.
- [ ] 5.3 Limitations не теряются downstream.
- [ ] 5.4 Invalid handoff rejected.
- [ ] 5.5 Contradictory evidence not silently averaged.
- [ ] 5.6 Material finding can trigger replanning.
- [ ] 5.7 Stop condition prevents unnecessary work.
- [ ] 5.8 No second LLM QC call is introduced.

## 6. Documentation and verification

- [ ] 6.1 Обновить architecture/product docs фактическими decisions.
- [ ] 6.2 Обновить roadmap.
- [ ] 6.3 Выполнить `python -m compileall app bot`.
- [ ] 6.4 Выполнить `python -m pytest`.
- [ ] 6.5 Выполнить `openspec validate add-orchestrator-quality-gates --strict`.
- [ ] 6.6 Сообщить фактические результаты, limitations, API changes и migrations.

