# SMM AI Helper Web Foundation

Independent mock-data frontend; no backend changes, no real authentication or model calls.

## Run

```bash
cd web
npm install
npm run dev
```

Open http://localhost:3000. Run `npm run lint` and `npm run build` before PR review.

## Boundaries

- All demo content is local mock data.
- Do not expose `BOT_BACKEND_TOKEN` or spoof `X-Telegram-User-ID` in browser requests.
- Replace mocks with versioned API clients only after SaaS auth and tenant ownership are implemented.
- This UI is a foundation, not a production-ready service.
