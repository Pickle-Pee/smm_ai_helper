# AI Marketing System

## Product intent

`smm_ai_helper` развивается из набора генераторов в Telegram-first AI marketing copilot: систему, которая сохраняет контекст бизнеса, помогает принимать маркетинговые решения, выполняет специализированную работу и объясняет достаточную decision logic без раскрытия скрытой chain-of-thought.

Первый продуктовый вертикальный сценарий:

```text
Competitor analysis
→ Commercial creative package
→ Mentor explanation
```

Система не гарантирует коммерческий результат. Она формирует обоснованные рекомендации, гипотезы и способы проверки, отделяя доступные evidence от assumptions.

## Conceptual layers

### 1. Expert Core

Общий слой правил мышления для всех маркетинговых модулей:

- business before vanity metrics;
- evidence first;
- facts, observations, inferences, hypotheses, assumptions, forecasts и recommendations не смешиваются;
- confidence соответствует силе evidence;
- economics, customer behavior, causality, currentness, ethics и operational reality учитываются там, где релевантны;
- simple request получает прямой ответ, complex request — приоритетный синтез;
- learning mode включается только явно.

### 2. Marketing Orchestrator

Управляющий слой, который:

- интерпретирует requested output, decision goal и business goal;
- проверяет root problem и достаточность контекста;
- выбирает минимально достаточный набор модулей;
- строит dependency-aware plan;
- передаёт каждому модулю релевантный context packet;
- оценивает результат по quality gates;
- перепланирует следующий шаг при material findings;
- синтезирует единый пользовательский результат;
- прекращает работу при достижении stop condition.

Orchestrator не является универсальным CMO и не подменяет специализированные модули.

Текущий runtime foundation реализует только deterministic planning и всегда возвращает `PLANNING_ONLY`. Quality Gates, replanning, synthesis и execution из полного product concept не следует считать уже подключённым поведением.

Планируемый Quality Gates foundation принимает только caller-supplied typed normalized results и возвращает deterministic structural decisions. Он не вызывает LLM/QC/modules, не читает persistence/context и не доказывает semantic truth. Пользовательский synthesis остаётся отдельной будущей интеграцией; foundation может сформировать только manifest eligibility.

### 3. Module Registry

Декларативный источник маршрутизации. Для каждого модуля описывает:

- `module_id`;
- тип и назначение;
- `use_when` и `do_not_use_when`;
- required, preferred, optional и blocking inputs;
- outputs;
- tool capabilities;
- quality gate;
- common handoffs;
- aliases.

Registry не исполняет задачи и не содержит бизнес-состояние.

### 4. Specialized modules

Нормативный набор production registry:

- `VIRTUAL_CMO`;
- `BUSINESS_DIAGNOSTICS`;
- `MARKET_ANALYSIS`;
- `COMPETITOR_ANALYSIS`;
- `POSITIONING`;
- `AD_AUDIT`;
- `CJM`;
- `CUSTDEV`;
- `CREATOR`;
- `COPY_EDITOR`;
- `LEAD_MAGNET`;
- `TREND_MONITORING`;
- `EXPERIMENTS`;
- `PROJECT_DEFENSE`;
- `MENTOR`.

### 5. Execution infrastructure

```text
Telegram / API
→ MarketingWorkflowService
→ MarketingRun / MarketingArtifact / Job
→ Redis transport
→ workers
→ PostgreSQL
→ Telegram delivery
```

PostgreSQL — durable source of truth. Redis — transport и coordination, но не business storage.

## Runtime boundaries

- `TaskPipelineService` остаётся single-task pipeline.
- Multi-module orchestration не внедряется внутрь `TaskPipelineService`.
- `MarketingWorkflowService` владеет orchestration multi-step marketing runs.
- Существующие `UrlAnalyzer` и `ImageOrchestrator` переиспользуются.
- `BrandProfile` остаётся durable brand context.
- `Conversation.facts_json` остаётся временным conversation context и не переписывает автоматически `BrandProfile`.
- Telegram handlers и API routers остаются thin.

## Shared decision vocabulary

### Claim type

`FACT`, `OBSERVATION`, `INFERENCE`, `HYPOTHESIS`, `ASSUMPTION`, `FORECAST`, `RECOMMENDATION`.

### Confidence

`HIGH`, `MEDIUM`, `LOW`, `UNKNOWN`.

### Module status

`PASS`, `PASS_WITH_LIMITATIONS`, `FAIL`, `BLOCKED`.

### Input dependency

`REQUIRED`, `PREFERRED`, `OPTIONAL`, `BLOCKING`.

### Priority

`P0`, `P1`, `P2`, `LATER`.

## Non-goals

- Не создавать один универсальный mega-agent.
- Не копировать полный CORE в каждый module prompt.
- Не запускать максимальное количество модулей ради полноты.
- Не превращать prompt text в недокументированную runtime-архитектуру.
- Не выдавать synthetic AI personas за customer evidence.
- Не пытаться детерминированным кодом доказать истинность произвольного маркетингового вывода.
- Не показывать пользователю внутренний routing trace или hidden chain-of-thought.
- Не считать contract completeness доказательством истинности claim.
- Не повышать confidence из-за повторения claim или непроверенной «независимости» нового evidence.
- Не подключать существующие agent dictionaries к normalized Quality Gates без явного adapter contract.

## Product success criteria

- Система выбирает подходящий, а не самый мощный модуль.
- Повторный вызов модуля не выполняется без новых данных или material value.
- Downstream output сохраняет provenance, assumptions, confidence и limitations upstream claims.
- Простые задачи не превращаются в длинные workflow.
- Комплексные задачи дают единый приоритетный результат, а не dump outputs модулей.
- Пользователь понимает, что рекомендуется, почему и как проверить.

