## 1. Canonical Expert Core Policy

- [ ] 1.1 Add `app/prompts/expert_core/v1.0.0.md` as the sole canonical runtime instruction body and add only the minimal Python resource loader/version metadata needed by the composer; verify the loader reads that deployed Markdown resource and no Python module, agent prompt, DOCX, or other runtime file duplicates or supplies the runtime body, while archival documentation remains non-runtime.
- [ ] 1.2 Add deterministic initial-fidelity tests that verify sections 1–59 each exist exactly once and in order, every number has the exact expected title from the design manifest, section 56 contains the expected `NEVER` and `ALWAYS` groups and entries, and the version has valid `MAJOR.MINOR.PATCH` form; optionally record and verify a SHA-256 checksum using the design's normalization algorithm.
- [ ] 1.3 Update the existing `docs/product/expert-core.md` with canonical-resource provenance, product-policy and engineering ownership, the `1.0.0` initial-version assumption, semantic-version rules, review/change process, version history, and the rule that compression or weakening requires a separately reviewed versioned change; do not create `docs/expert-core.md`.
- [ ] 1.4 Update `docs/product/prompt-source-map.md`, `docs/development/prompt-governance.md`, and the archival `docs/product/prompts/expert-core-production.md` notice so they all identify `app/prompts/expert_core/v1.0.0.md` as the only canonical runtime source and identify DOCX/archival Markdown/product-contract roles consistently.

## 2. Shared Instruction Composition Boundary

- [ ] 2.1 Add the immutable composition value and pure composer in `app/services/expert_instruction_composer.py`; verify it renders components in the deterministic order Expert Core → specialized module → optional response mode and returns the active version as metadata.
- [ ] 2.2 Implement explicit precedence text and component boundaries; verify non-negotiable Expert Core evidence, safety, currentness, and ethics authority is stated without altering non-conflicting module method or presentation instructions.
- [ ] 2.3 Implement idempotent handling for an already composed instruction value and exactly-one-core validation; verify a repeated composition retains the same version, text, and component order without adding a second core.
- [ ] 2.4 Reject empty/invalid canonical policy data and raw module or response-mode text containing reserved core markers; verify the dedicated composition error is raised before any external model-call fake is invoked and no module-only fallback is produced.

## 3. Existing Standalone-Agent Integration

- [ ] 3.1 Update both `BaseAgent.llm_text` and `BaseAgent.llm_json` to use the shared composer immediately before the existing `openai_text.chat` call; verify text requests retain the module prompt and JSON requests retain the current strict-JSON/schema-hint instructions.
- [ ] 3.2 Verify `AgentRunner` responsibilities and routing behavior remain unchanged.
- [ ] 3.3 Verify `TaskPipelineService` responsibilities, task state transitions, and existing task-pipeline regression behavior remain unchanged.
- [ ] 3.4 Verify each agent-specific prompt, schema hint, parser, presenter, and result dictionary retains its existing module-specific contract.
- [ ] 3.5 Verify model selection, model overrides, `TOKEN_BUDGETS`, and `MAX_OUTPUT_TOKENS_CAP` remain unchanged.
- [ ] 3.6 Verify existing QC behavior and model-call count remain unchanged and no Expert Core-specific QC request is introduced.
- [ ] 3.7 Verify no public API/schema, database/model/migration, Redis, queue, worker, Job, or marketing-workflow behavior change is present.
- [ ] 3.8 Add registry-wide deterministic coverage proving `strategy`, `content`, `analytics`, `promo`, and `trends` all reach the shared base composition boundary on their generation requests, and make the test fail if a future registered standalone marketing agent bypasses it.
- [ ] 3.9 Add model-call spy tests proving each individual covered request contains one core, a multi-request agent receives one core per request, and Expert Core adoption creates no additional OpenAI or QC request.

## 4. Version Diagnostics and Compatibility

- [ ] 4.1 Emit `expert_core_version` and agent identity in internal request-construction diagnostics, extending the existing logging context only if needed; verify logs contain the active version but not the full core, module prompt, user material, or credentials.
- [ ] 4.2 Add compatibility tests or assertions showing existing standalone-agent result dictionaries and presenters retain their module-specific shapes and that no universal Expert Core response schema or new public response field is introduced.
- [ ] 4.3 Create `docs/development/expert-core-verification.md` and record the canonical instruction character/word size, token-estimation method and result, composition order, exactly-one-stable-prefix evidence, normalized checksum when used, and whether staging token/latency data was available; confirm that `TOKEN_BUDGETS` and `MAX_OUTPUT_TOKENS_CAP` were not increased to compensate for input growth.

## 5. Verification and Scope Audit

- [ ] 5.1 Run `pytest` and confirm all deterministic unit/regression tests pass without real OpenAI, Telegram polling, or uncontrolled external HTTP calls.
- [ ] 5.2 Run `python -m compileall app bot` and confirm compilation succeeds.
- [ ] 5.3 Run `openspec validate add-expert-core-foundation --strict` and confirm the change validates.
- [ ] 5.4 Run `openspec validate --all --strict` and confirm all repository OpenSpec artifacts validate.
- [ ] 5.5 Run `git diff --check`, review the final diff, and confirm there are no public API/schema changes, database models or migrations, Redis/queue/worker/job additions, workflow implementation, new model-based QC calls, copied core prompts in agent files, or unrelated refactors.
