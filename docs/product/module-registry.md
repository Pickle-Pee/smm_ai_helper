# Module Registry product contract

## Responsibility

MODULE REGISTRY отвечает только на вопросы:

- какой модуль существует;
- когда он применим;
- какие inputs ему нужны;
- что он обязан вернуть;
- какие tools/capabilities допустимы;
- куда возможен handoff.

Канонический prompt: [`prompts/module-registry-production.md`](prompts/module-registry-production.md).

## Canonical module IDs

`VIRTUAL_CMO`, `BUSINESS_DIAGNOSTICS`, `MARKET_ANALYSIS`, `COMPETITOR_ANALYSIS`, `POSITIONING`, `AD_AUDIT`, `CJM`, `CUSTDEV`, `CREATOR`, `COPY_EDITOR`, `LEAD_MAGNET`, `TREND_MONITORING`, `EXPERIMENTS`, `PROJECT_DEFENSE`, `MENTOR`.

## Module descriptor

Каждая запись registry должна иметь:

- stable `module_id`;
- module type;
- purpose;
- `use_when`;
- `do_not_use_when`;
- required/preferred/optional/blocking inputs;
- declared outputs;
- tool flags;
- quality gate;
- common handoffs;
- aliases;
- authority limitations.

## Activation contract

```text
MODULE_ID
OBJECTIVE
USER_GOAL
REQUIRED_OUTPUT
RELEVANT_CONTEXT
KNOWN_FACTS
UPSTREAM_FINDINGS
EVIDENCE
ASSUMPTIONS
CONFIDENCE
CONSTRAINTS
AVAILABLE_TOOLS
OPEN_QUESTIONS
```

## Return contract

```text
MODULE_ID
STATUS
SUMMARY
FINDINGS
EVIDENCE
ASSUMPTIONS
HYPOTHESES
RECOMMENDATIONS
RISKS
CONFIDENCE
OPEN_QUESTIONS
STRATEGIC_ISSUES
HANDOFF_RECOMMENDATION
```

## Registry invariants

- Один canonical descriptor на `module_id`.
- Aliases разрешаются в canonical IDs.
- Registry не хранит user/project state.
- Registry не исполняет модули.
- Module не расширяет authority за пределы descriptor.
- Повторное выполнение не требуется, если relevant output уже актуален и новый вызов не изменит решение.
- Добавление/изменение module descriptor требует tests и OpenSpec change.

