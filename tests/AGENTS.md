# Test instructions

These rules extend the repository-level `AGENTS.md` for work under `tests/`.

- Tests must be deterministic and isolated.
- Unit tests must not call real OpenAI APIs, real Telegram polling, or uncontrolled external HTTP endpoints.
- Mock or fake external integrations at service boundaries.
- Prefer testing public service behavior over internal implementation details.
- Add regression coverage for fixed bugs when practical.
- New OpenSpec scenarios should be traceable to tests or an explicit manual verification step.
- Keep integration tests clearly separated when they require PostgreSQL, Redis, filesystem persistence, or other infrastructure.
- Do not claim test success unless the command was actually run and returned successfully.