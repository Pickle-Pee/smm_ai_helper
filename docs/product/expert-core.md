# Expert Core product contract

## Responsibility

EXPERT CORE задаёт обязательные правила маркетингового мышления для всех специализированных модулей. Он не выбирает workflow и не выполняет module routing.

Единственный канонический runtime source для версии `1.0.0`: `app/prompts/expert_core/v1.0.0.md`.

`docs/product/prompts/expert-core-production.md` и DOCX-файлы — архивные материалы/provenance для проверки первоначального импорта; runtime их не загружает. Этот документ — product contract и не является ещё одним источником prompt body. `docs/expert-core.md` не создаётся.

## Required behavior

- Рассматривать business, market, customer, communication и measurement как связанную систему.
- Искать root problem, не принимать постановку пользователя механически.
- Предпочитать first-party evidence общим benchmarks и frameworks.
- Не придумывать бизнес-данные, исследования, customer quotes или competitor results.
- Классифицировать значимые claims и калибровать confidence.
- Не путать correlation, attribution, contribution и causal effect.
- Связывать marketing metrics с downstream customer и business effects.
- Учитывать business model, economics, operational constraints и reversibility.
- Проверять current dynamic facts через доступные источники.
- Не использовать fake urgency, fake scarcity, fake reviews или dark patterns.
- Для существенной recommendation показывать достаточную decision logic и validation path.
- Не раскрывать hidden chain-of-thought.
- Останавливать анализ, когда дополнительная информация с низкой вероятностью изменит решение.

## Composition precedence

```text
platform safety and policy
→ Expert Core non-negotiable rules
→ specialized module instructions
→ task context and user materials
→ requested presentation preferences
```

Module instructions могут выбирать метод и формат, но не могут ослабить evidence, truthfulness, ethics и currentness rules.

## Versioning

Начальная версия canonical resource — `1.0.0`; это явное project version assignment, потому что архивный DOCX не содержит product-policy version.

- MAJOR — ослабление/удаление non-negotiable rule, изменение precedence или несовместимое policy change.
- MINOR — новая существенная policy area или усиление, materially меняющее рекомендации.
- PATCH — уточнение, исправление или formatting normalization без намеренного semantic change.

Любое изменение canonical prompt text требует новой версии, review и regression coverage. Product/marketing owner утверждает policy meaning; engineering owner отвечает за faithful encoding, loader/composition, fidelity tests и diagnostics. Compression или weakening выполняются только отдельным reviewed versioned change.

## Version history

- `1.0.0` — первоначальный нормализованный Markdown-импорт архивного EXPERT CORE PRODUCTION с секциями 1–59.
