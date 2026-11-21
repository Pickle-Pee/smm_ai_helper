# B2.2 HTTP authentication

The normative contract is web PR #17 at db1135fccbc4ca6e316b6e2123bfb23c99a62af8. Public routes use the [web OpenAPI](https://github.com/Pickle-Pee/smm_ai_helper_web/blob/db1135fccbc4ca6e316b6e2123bfb23c99a62af8/docs/api/web-api-v2.openapi.yaml). The test fixture includes the referenced response schemas and the published exchange example from that revision.

Both WEB_API_ENABLED and WEB_TELEGRAM_LOGIN_ENABLED default to false. With API off every /v2 route returns 404. With only API on both Telegram operations return 403 feature_disabled. CSRF and logout continue to work with live sessions. Before disabling the entire API, expire or revoke remaining sessions. An enabled API requires a canonical HTTPS WEB_APP_ORIGIN and a separate WEB_CSRF_SECRET containing at least 32 bytes of random server-side key material shared by replicas. Plan key rotation with session revocation.

| Method and path | Behavior with both flags enabled |
|---|---|
| POST /v2/auth/telegram/challenge | Same-origin, live single-use grant, 200 with confirmation code and host-only attempt cookie after commit |
| POST /v2/auth/telegram/exchange | Same-origin, matching confirmed attempt, atomic B2.1 exchange plus onboarding. Missing B3/B4 returns 503 and rolls back. Cookie and AuthSession follow successful commit |
| GET /v2/auth/csrf | 200 with stable HMAC token for a live server session, otherwise 401 |
| POST /v2/auth/logout | Same-origin, CSRF if session exists, commit revocation before clearing cookie. Repeated logout returns 204 |
| GET /v2/me | 401 without live session, 503 until active personal membership is available, otherwise the allowlisted Me projection |

B2.3 owns bot confirmation in private Telegram chat. B3/B4 must implement the membership reader for the authenticated users.id and complete idempotent personal org/project provisioning and brand import in the exchange transaction. Tests substitute the published membership fixture only at that boundary. B2.4 owns trusted-edge rate limits, access-log redaction and HTTPS rollout. Production 0015/0016 and public beta isolation gate #219 require separate release decisions.
