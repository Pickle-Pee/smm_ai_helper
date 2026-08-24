# Expert Core verification

## Canonical resource

- Runtime source: `app/prompts/expert_core/v1.0.0.md`.
- Active version: `1.0.0`.
- Runtime loader: `app.prompts.expert_core.load_expert_core`.
- DOCX files and `docs/product/prompts/expert-core-production.md` are archival provenance and are not loaded by the application.

## Initial-import fidelity

Normalization used for the recorded checksum:

1. decode as UTF-8 and remove a leading UTF-8 BOM if present;
2. convert CRLF and CR line endings to LF;
3. remove trailing spaces and tabs from each line;
4. remove trailing blank lines;
5. calculate SHA-256 over normalized UTF-8 bytes.

Measured result:

- sections: `59`, numbered 1 through 59 exactly once and in order;
- expected titles: all 59 matched the design manifest;
- section 56: exact expected `NEVER` and `ALWAYS` groups matched;
- normalized SHA-256: `5dad2b61b14c6a137668bd7ed0a5ee3b5cff45235d7c79726337b1e3529d72f9`.

## Size and token estimate

Measurements use the normalized canonical text:

- Unicode characters: `33,241`;
- UTF-8 bytes: `49,876`;
- whitespace-delimited words: `3,783`;
- deterministic token approximation: `ceil(characters / 4) = 8,311`.

The repository has no configured tokenizer dependency, so the token figure is an approximation rather than provider billing usage. No live staging token or latency measurement was available in this environment. `TOKEN_BUDGETS` and `MAX_OUTPUT_TOKENS_CAP` were not changed; they limit output tokens and were not increased to compensate for the new input prefix.

## Composition verification

Deterministic tests verify:

- component order is Expert Core → specialized module → optional response mode;
- the precedence declaration appears before the canonical policy;
- identical inputs produce identical immutable composition results;
- recomposing a valid composed value is idempotent;
- every model request contains exactly one Expert Core component;
- reserved markers, empty components, invalid versions, unavailable resources, and invalid composed boundaries fail before the external model call;
- both `BaseAgent.llm_text` and `BaseAgent.llm_json` use the shared boundary;
- all five registered agents inherit the same boundary;
- a multi-request `ContentAgent` run adds one core to each request without adding a request;
- diagnostics contain only version and agent identity, not prompt or user content.

## Packaging and deployment evidence

- `app/prompts/expert_core/v1.0.0.md` is loadable through `importlib.resources` from the application package tree.
- `Dockerfile` uses `WORKDIR /app` followed by `COPY . .`.
- No `.dockerignore` excludes `app/prompts`.
- Both backend and bot services build from this Dockerfile.
- The resulting image path is therefore `/app/app/prompts/expert_core/v1.0.0.md`.
- The repository has no wheel/sdist configuration; Python currently runs directly from the copied tree.
- A deterministic test asserts the package resource and Docker build-context conditions.
- Docker client `29.6.1` was available, but the Docker daemon was not running, so an image build/runtime file check could not be executed locally.

If wheel/sdist packaging is introduced, its package-data configuration and installed-package test must explicitly preserve the Markdown resource.

## Commands and results

- `pytest -q ...` — did not start because `pytest` was not in PowerShell `PATH`.
- `python -m pytest ...` — did not start because system Python 3.14 did not have pytest.
- Created ignored local `.venv` with bundled Python 3.12 and installed `requirements.txt`.
- `.venv\Scripts\python.exe -m pytest -q tests/test_expert_core.py tests/test_expert_core_integration.py tests/test_agent_registry.py tests/test_agent_input_builder.py tests/test_agent_output_builder.py tests/test_task_pipeline_service.py` — `36 passed, 1 warning`.
- `.venv\Scripts\python.exe -m pytest -q` — `111 passed, 9 warnings`.
- `.venv\Scripts\python.exe -m compileall app bot` — passed.
- Direct loader/composer import smoke check — passed; version `1.0.0`, resource length `33,241`, component order `expert_core → specialized_module → response_mode`.
- `openspec validate add-expert-core-foundation --strict` — valid.
- `openspec validate --all --strict` — `8 passed, 0 failed`.
- `docker version --format ...` — client available; daemon unavailable, so no image build was performed.
