## 1. Canonical Expert Core Policy

- [ ] 1.1 Add `app/prompts/expert_core.py` with the single executable Expert Core instruction source, reserved component identity markers, and initial semantic version `1.0.0`; verify the normalized transcription preserves the policy meaning of all 59 sections in `agents_prompts/1. EXPERT CORE PRODUCTION.docx` without runtime DOCX loading.
- [ ] 1.2 Add deterministic source tests that verify the core is non-empty, the version has valid `MAJOR.MINOR.PATCH` form, sections 1–59 and the non-negotiable policy categories are represented, and no registered agent file contains a full copied core or reserved core marker.
- [ ] 1.3 Add `docs/expert-core.md` documenting the normative-source provenance, product-policy and engineering ownership, initial-version assumption, semantic version rules, review/change process, version history, and the rule that policy compression or weakening requires a separately reviewed versioned change.

## 2. Shared Instruction Composition Boundary

- [ ] 2.1 Add the immutable composition value and pure composer in `app/services/expert_instruction_composer.py`; verify it renders components in the deterministic order Expert Core → specialized module → optional response mode and returns the active version as metadata.
- [ ] 2.2 Implement explicit precedence text and component boundaries; verify non-negotiable Expert Core evidence, safety, currentness, and ethics authority is stated without altering non-conflicting module method or presentation instructions.
- [ ] 2.3 Implement idempotent handling for an already composed instruction value and exactly-one-core validation; verify a repeated composition retains the same version, text, and component order without adding a second core.
- [ ] 2.4 Reject empty/invalid canonical policy data and raw module or response-mode text containing reserved core markers; verify the dedicated composition error is raised before any external model-call fake is invoked and no module-only fallback is produced.

## 3. Existing Standalone-Agent Integration

- [ ] 3.1 Update both `BaseAgent.llm_text` and `BaseAgent.llm_json` to use the shared composer immediately before the existing `openai_text.chat` call; verify text requests retain the module prompt and JSON requests retain the current strict-JSON/schema-hint instructions.
- [ ] 3.2 Keep `AgentRunner`, `TaskPipelineService`, agent-specific prompts, schema hints, parsers, presenters, model selection, QC behavior, and output-token settings functionally unchanged; verify existing agent input/output and task-pipeline regression tests still pass.
- [ ] 3.3 Add registry-wide deterministic coverage proving `strategy`, `content`, `analytics`, `promo`, and `trends` all reach the shared base composition boundary on their generation requests, and make the test fail if a future registered standalone marketing agent bypasses it.
- [ ] 3.4 Add model-call spy tests proving each individual covered request contains one core, a multi-request agent receives one core per request, and Expert Core adoption creates no additional OpenAI or QC request.

## 4. Version Diagnostics and Compatibility

- [ ] 4.1 Emit `expert_core_version` and agent identity in internal request-construction diagnostics, extending the existing logging context only if needed; verify logs contain the active version but not the full core, module prompt, user material, or credentials.
- [ ] 4.2 Add compatibility tests or assertions showing existing standalone-agent result dictionaries and presenters retain their module-specific shapes and that no universal Expert Core response schema or new public response field is introduced.
- [ ] 4.3 Measure and document the canonical instruction character/word size in the implementation review, verify exactly one stable core prefix is sent per covered request, and confirm that `TOKEN_BUDGETS` and `MAX_OUTPUT_TOKENS_CAP` were not increased to compensate for input growth.

## 5. Verification and Scope Audit

- [ ] 5.1 Run `pytest` and confirm all deterministic unit/regression tests pass without real OpenAI, Telegram polling, or uncontrolled external HTTP calls.
- [ ] 5.2 Run `python -m compileall app bot` and confirm compilation succeeds.
- [ ] 5.3 Run `openspec validate add-expert-core-foundation --strict` and confirm the change validates.
- [ ] 5.4 Run `openspec validate --all --strict` and confirm all repository OpenSpec artifacts validate.
- [ ] 5.5 Run `git diff --check`, review the final diff, and confirm there are no public API/schema changes, database models or migrations, Redis/queue/worker/job additions, workflow implementation, new model-based QC calls, copied core prompts in agent files, or unrelated refactors.
