# AI Marketing System

## Product intent

`smm_ai_helper` развивается из набора генераторов в Telegram-first AI marketing copilot: систему, которая сохраняет контекст бизнеса, помогает принимать маркетинговые решения, выполняет специализированную работу и объясняет достаточную decision logic без раскрытия скрытой chain-of-thought.

Реализованный фиксированный MVP-сценарий:

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

Полный продуктовый замысел управляющего слоя (перечень шире текущей реализации):

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

Текущий generic Orchestrator реализует только deterministic planning и всегда возвращает `PLANNING_ONLY`. Generic execution, autonomous replanning и synthesis из полного product concept не подключены. Отдельный фиксированный MVP уже исполняется через `MarketingWorkflowService` и три явных workflow-specific executor; это не исполнение произвольного плана Orchestrator.

Quality Gates в `app/marketing_orchestrator/quality_gates/` принимает caller-supplied typed normalized results и возвращает deterministic structural decisions. Confidence использует только `UNKNOWN < LOW < MEDIUM < HIGH`; identities и lineage явные, timestamps caller-supplied и UTC-normalized. `app/workflows/quality.py` уже связывает evaluator с fixed MVP: проверяет claims, evidence и lineage до сохранения MarketingArtifact. Сам evaluator не вызывает LLM/QC/modules, не читает persistence/context и не доказывает semantic truth. Его Registry-derived readiness остаётся `PLANNING_ONLY`; fixed workflow использует gate outcomes и eligibility manifest. Generic user-facing synthesis остаётся будущей работой.

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

Registry `1.0.0` содержит только metadata, имеет ноль execution bindings, не исполняет задачи и не содержит бизнес-состояние. Fixed executors используют metadata и Expert Core composition, но не добавляют Registry bindings.

### 4. Specialized modules

Нормативный набор metadata Registry (15 описаний, а не 15 работающих исполнителей):

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
→ Redis wakeups + PostgreSQL due scan
→ fixed workflow workers / JobExecution
→ PostgreSQL
→ Telegram delivery
```

PostgreSQL — durable source of truth. Redis — transport и coordination, но не business storage.

### Durable Job persistence boundary

`add-durable-job-persistence` реализован: модель, сервис и миграция `20260825_0004` присутствуют. `Job` — одна durable execution request, уже используемая асинхронным MVP, а не копия workflow state или output:

- `MarketingRun` хранит состояние и прогресс multi-step workflow;
- `MarketingArtifact` хранит именованный reusable output шага;
- `Job` хранит request input, immutable через supported persistence service, и lifecycle `pending -> running -> succeeded|failed`.

Job является operational child `MarketingRun`, direct user или trusted-internal system record без owner reference; public anonymous Job creation отсутствует. Удаление run/user каскадно удаляет owned Jobs, а не превращает их в system work; retained audit history не входит в foundation. Commit/rollback принадлежит вызывающему transaction owner; fixed workflow атомарно сохраняет artifact, Job outcome, run transition и delivery parts в PostgreSQL.

Сам persistence service не исполняет Job. Уже реализованный workflow layer публикует Redis wakeups, восстанавливает работу через PostgreSQL due scan и хранит bounded attempts, leases, fencing и retry availability в `JobExecution`, не меняя закрытый lifecycle Job. Независимая durable Telegram delivery имеет собственные claims/retries/acknowledgements и не повторяет генерацию. Потеря Redis не теряет работу; неоднозначный provider timeout или Telegram send до потери acknowledgement может дать повторный внешний эффект.

## Fixed MVP scope implemented now

- Анализ доступного текста одной публичной HTML-страницы конкурента с сохранённым snapshot BrandProfile и текущей цели.
- Коммерческий пакет на основе сохранённого анализа: offer, headline, CTA, баннер через существующий ImageOrchestrator и сценарий Reels/Shorts.
- Mentor explanation на основе сохранённых analysis/creative artifacts только после явного действия пользователя.
- Durable artifacts с evidence, assumptions, limitations и lineage; Quality Gates adapter до записи.
- Owner-scoped API/workflow/media, background execution/recovery, повторное использование существующей работы и независимая доставка в Telegram.

Контракты и ограничения: [fixed workflow](../development/marketing-mvp.md). Generic Orchestrator execution, arbitrary 15-module execution, autonomous replanning, generic synthesis, campaign execution, CRM, финальная генерация/монтаж видео и production deployment не реализованы. Exactly-once provider/Telegram semantics не обещаются.

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

