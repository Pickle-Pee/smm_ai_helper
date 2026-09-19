# Telegram Copilot UX (Task K)

The primary private-chat free-text route uses the production API merged in PR #64.
Telegram is an HTTP transport and presentation adapter, with no LLM intent router,
executor bindings, database/Redis access or graph execution. No migrations.

```text
message -> existing explicit command/task/image handlers, when applicable
        -> chat.chat_message -> copilot_flow.receive
           -> explicit URL-role UI / pending clarification
           -> CopilotClient POST /copilot/execute
              CONVERSATION       -> existing /chat/message HTTP integration
              DIRECT_RESULT      -> inputs + human formula + result + assumptions
              MODULE_RESULT      -> post or readable findings/sources/limitations
              NEEDS_INPUT        -> grouped clarification / website confirmation
              WORKFLOW_STARTED   -> acknowledgement + stateless status button
                                      |
                  existing backend Jobs / graph worker / PostgreSQL artifacts
                                      |
status button -> CopilotClient GET /copilot/runs/{run_id} -> result sections
```

## Boundary and routing

`bot/copilot_client.py` sends the existing bearer token and `X-Telegram-User-ID`.
Callbacks use the clicking actor, never the bot message's sender. The backend
remains the ownership authority; foreign and unknown runs have the same generic
«Результат не найден.» presentation. No caller-provided status URL is fetched:
GET paths are built from a validated run ID against the configured backend.

The client has a 10-second connection timeout, a 300-second read/write/pool timeout
and a 310-second total bound. This accommodates the API's default 300-second
execution budget. There are no hidden HTTP retries. It validates public responses
and keeps errors free of response bodies. Logs contain only actor, request key,
result kind, run ID and HTTP status, not message/context/site/token/provider data.

`bot/copilot_contracts.py` is the independent client-side mirror of the pinned
`copilot_api.v1` wire contract. Schema-parity tests cover request, execute response,
run response and error response. Importing the backend Copilot package would load
planning/Registry dependencies, so the bot deliberately does not share that
package's Python classes. An import guard checks both source and fresh-process
transitive imports.

`create_dispatcher()` retains menu, fixed workflow, standalone agent/image and
history handlers ahead of primary free text. Primary free text matches only an
empty FSM or Copilot pending state. Existing `/analyze`, `/brand`, `/context`,
`/runs`, `/status`, `/result`, `/redeliver`, task callbacks and explicit image flow
keep their original HTTP endpoints. Legacy action callbacks remain legacy actions.
New general text goes to Copilot first; when it returns `CONVERSATION/legacy_chat`,
the adapter calls the existing `_send_to_backend` once without a second answer.
Natural-language image behavior is available through that existing delegation;
the explicit image UI is unchanged. No new Copilot image generation is added.

## Request identity and FSM

The initial key is `tg:{actor_id}:{chat_id}:{message_id}`. Telegram message IDs are
stable within the chat, so redelivery derives the same key. No random key is
generated for transport retries. `NEEDS_INPUT` preserves this logical identity
while accumulating explicit context. A terminal synchronous response clears the
pending request; the next independent message derives its own key. `/new` or
«Начать новый запрос» clears the pending request and asks for a new message; that
message supplies the new deterministic key.

Aiogram's existing MemoryStorage is used with `SimpleEventIsolation` to serialize
messages and callbacks for each FSM key. Pending data contains:

- request key, original message and current public request payload;
- explicit scalar context, owned URL, competitor URLs, market URLs/excerpts;
- last grouped clarification requirements and next scalar field;
- unclassified/classified URLs, snapshot candidates and explicitly selected indices;
- presentation phase and revision-bound callback token.

Only indices into the saved API candidates are accepted by selection buttons;
statement IDs are never parsed from user text. Revision tokens invalidate old
URL/clarification/retry keyboards. A bounded ledger of the latest 64 message and
callback identities suppresses recent redeliveries, including duplicate scalar
answers and selection toggles. It is a convenience, not durable deduplication.
The backend actor/key/plan identity is the durable protection against duplicate
workflow creation; identical replay returns the same run and set of Jobs.

After `WORKFLOW_STARTED`, pending context is dropped. FSM retains only `run_id`,
`status_url` and `request_key`, without a local workflow status. Status buttons
encode the 32-byte run ID as canonical unpadded base64url (`cs:` + 43 characters),
fitting Telegram's 64-byte callback limit. Decoding restores the exact public
64-hex ID without a lookup table. `/copilot_status [run_id]` is also available.

## Clarification and sources

The API's alternatives are OR groups. Business scalar fields in the first group
are presented together with Russian wording, then collected in a guided sequence
under the same request key. No model chooses which field the answer belongs to.
Canonical target/product/geography aliases map to the public context fields.
Unknown or non-scalar requirements receive a grouped request for a revised message,
never internal canonical keys. In particular, API v1's calculator parses a full
message, so the bot gives a supported example such as
«Рассчитай лиды при бюджете 10000 и CPL 500». It preserves the original message in
FSM and sends the revised complete calculation text under the same logical key;
it does not invent numeric API fields or calculate in the bot.

Every newly supplied HTTP(S) URL, including text-link entities, receives an explicit
role choice before submission: «Мой сайт», «Конкурент», «Источник рынка», or
«Не использовать как источник». URL position never determines role. The UI permits
one owned URL, at most three competitors (with a visible counter), and at most three
market URLs; request DTO validation independently enforces list bounds. An initial
message may contain up to 20 links to classify, each at most 2048 characters.
Ignored links remain in the original text but are absent from source lists; the API
explicitly masks raw-message URL fallback. Backend safe-fetch validation remains
authoritative. For excerpts the pending payload preserves `market_sources`; v1 UI
collects market URLs rather than introducing a new excerpt editor.

An owned URL is submitted only in `owned_site_url`. Eligible API candidates are
displayed as «На сайте указано: …» with their source, explicitly unverified. Nothing
is preselected. The user selects statements and then presses «Подтвердить данные
сайта». Only that action adds snapshot ID, selected statement IDs, `confirmed=true`
and a bounded `tg-confirm:` SHA-256 reference derived from the callback identity.
The backend re-acquires and validates the snapshot; it supplies authenticated
attester identity. Manual product facts remain an alternative.

On `409 confirmation_changed`, the old confirmation is removed, fresh candidates
are displayed with an empty selection and explicit reconfirmation is required.
If fresh candidates are unavailable, the user can enter product facts manually.
Source acquisition failures use safe Russian messages, never extraction details.

## Results, retries and cancellation

All Copilot text uses the existing `send_text` with explicit `parse_mode=None`.
Model/user/source strings are literal plain text, so HTML and Markdown cannot
create entities or break the layout. Each logical section is sent separately;
the shared deterministic UTF-16 splitter bounds oversized sections at 3500 units,
preserving all text and whole Unicode characters. No LLM rewrite/summarization.

Posts include headline, body, CTA and limitations. Findings include translated
section labels, human confidence wording, sources and limitations. Strategy output
includes strategic diagnosis, growth constraint, priorities, trade-offs, resource
priorities, strategic bets, roadmap, risks and decision triggers. Experiments follow
as a separate block. Evidence coverage displays accepted/supplied competitors;
missing market research, unavailable competitors/economics and other limitations
are visible in a separate warning block. Known API boilerplate is deterministically
translated; other public result/limitation prose retains the API's original language.

QUEUED/RUNNING have short status messages and another status button. Completed
runs render saved results. COMPLETED_WITH_LIMITATIONS adds a distinct limitations
block. BLOCKED uses the API's public reason/action (translated when known). FAILED
shows only «Не удалось завершить запрос. Можно попробовать снова.»

Network errors, backend authentication/configuration errors, invalid client state
(422), conflicts (409), temporary unavailability (503), malformed responses and
unexpected server failures have separate safe handling. «Повторить» reuses the
unchanged payload/key after network/503/server failure; synchronous responses are
not durably cached by the backend, so such retries can repeat synchronous work.
`request_conflict` never silently changes the key or auto-retries with new context;
the user must start a new request. `/cancel` clears pre-run pending data. An already
started analysis cannot be cancelled through Telegram v1; no graph status is changed.

## Restart and delivery limits (Task L)

No automatic status polling or new delivery loop is introduced. User-triggered GETs
are the only Copilot status checks; the existing fixed-workflow delivery poller is
unchanged. Backend PostgreSQL is authoritative and workers continue independently.

A bot restart loses unfinished clarification, candidate selections, source roles,
the recent event ledger and the convenience pointer for `/copilot_status` without
an ID. Old pre-run buttons tell the user to start again. Already delivered run
status buttons keep working after restart because they contain a reversible run
identity. If the process dies after backend acceptance but before Telegram receives
the acknowledgement, the user may lack that button. Durable continuation/recovery
and a Copilot run-list UX are explicitly deferred to Task L. Recent Telegram-event
deduplication and synchronous reply delivery are not exactly-once guarantees.

## Verification and manual checks

`tests/test_telegram_copilot.py` covers HTTP contract parity/security/errors, real
dispatcher routing and concurrent duplicate updates, context/URL/confirmation
state, stale callbacks, retries, cancellation, rendering and import boundaries.
`tests/test_telegram_copilot_postgresql.py` uses fake Telegram/provider capabilities
with real authenticated HTTP routing, production Copilot composition, PostgreSQL
and graph workers. It checks DIRECT, POST, CONVERSATION, strategy/experiments,
optional competitor failure, owned-site reacquisition, duplicate Jobs and foreign
ownership. The container CI smoke includes both suites with no Telegram polling.

Manual checks on a configured private-chat bot:

1. Send the calculation example; inspect inputs, formula, result and assumptions.
2. Request a post, then an ordinary conversation; each uses its intended result path.
3. Start a strategy without product facts, answer the grouped prompts, and check status.
4. Supply own/competitor/market links, explicitly classify each; test the fourth competitor limit.
5. Select only a subset of site claims and confirm. Change the page and verify reconfirmation.
6. Check completed/limited/failed strategy states, separate experiments and research coverage.
7. Restart only the bot; an earlier run status button must still work. Unfinished
   clarification must be restarted, as documented above.
8. Verify legacy `/analyze`, standalone task buttons, `/history` and image UI remain available.
