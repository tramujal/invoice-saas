# WhatsApp Assistant (Phase 23) — experimental, unofficial

## Status

**Experimental. Unofficial. Disabled by default. Not production-ready.**

This feature lets an organization talk to the existing AI Business
Assistant over WhatsApp — text or voice — instead of only the web UI. It
was built for portfolio demonstration and controlled testing, not as a
supported product feature.

It is **not** an official WhatsApp Business Platform / Meta Cloud API
integration. It is built on
[`whatsapp-web.js`](https://wwebjs.dev/), an unofficial library that
automates the WhatsApp Web client in a real, headless Chromium browser.
WhatsApp does not endorse this, and using it carries a real risk that the
connected phone number gets rate-limited or banned by WhatsApp — see
["Unofficial WhatsApp risks"](#unofficial-whatsapp-risks) below. **Do not
connect a phone number you cannot afford to lose**, and do not enable this
in front of real customers or real money.

The whole feature is off by default (`WHATSAPP_ENABLED=false`) and the
rest of the application is completely unaffected — starts, runs, and
passes its full test suite — whether or not any of this is configured.

## Architecture

```
WhatsApp (real phone) <--> whatsapp-web.js (headless Chromium)
                                   |
                     whatsapp-bridge/  (Node, transport ONLY)
                       - QR/session lifecycle
                       - inbound message normalization
                       - outbound send instructions
                                   |
                   signed HTTP (HMAC, see "Security model")
                                   |
                    FastAPI backend (app/whatsapp/)
                       - identity linking & verification
                       - RBAC, plan, quota, rate-limit checks
                       - hands off to the SAME AI assistant engine
                         the web UI uses (app/ai/engine.py)
                       - channel-specific reply formatting
                                   |
                          Postgres / SQLite
```

Two processes, two languages, one hard boundary between them:

- **`whatsapp-bridge/`** (Node/TypeScript) is transport-only. It never
  queries the application database, never evaluates permissions, never
  interprets a command, and never contains plan-limit logic. Its only job
  is: drive a WhatsApp Web session, normalize inbound messages into one
  JSON envelope, sign and forward that envelope to the backend, and later
  execute whatever outbound instruction (send text / send document /
  reconnect / …) the backend asks for. See its own module docstrings under
  `whatsapp-bridge/src/`.
- **`app/whatsapp/`** (Python) owns every business decision: who this
  phone number actually is, whether they're allowed to do this, what the
  AI assistant should do about it, and what to say back. It talks to the
  bridge only through the small `WhatsAppProvider` interface
  (`app/whatsapp/provider_base.py`) — never `whatsapp-web.js` objects
  directly, so a future second transport (see
  ["Migration path to the Meta Cloud API"](#migration-path-to-the-meta-cloud-api))
  can be added without touching anything above that interface.

### No second AI engine

The biggest architectural risk with a feature like this is quietly
building a second, slightly-different command interpreter. This phase
deliberately does not:

- `app/ai/engine.py`'s `run_chat_turn(...)` — the propose/tool-call loop
  — was extracted out of the HTTP assistant router specifically so
  `app/whatsapp/service.py` could call the exact same function the web
  chat UI calls, with the exact same `AIProvider`, `ActionTool` registry,
  and permission checks.
- `app/services/assistant_actions.py`'s `confirm_action` /
  `cancel_action` — likewise extracted out of the confirm/cancel HTTP
  router — is what WhatsApp's `CONFIRMAR` / `CANCELAR` commands call.
  Permission and plan/quota limits are re-checked at confirmation time
  exactly as they are for the web UI, because it's the same code.

`app/whatsapp/service.py` (the WhatsApp-specific layer) only ever adds:
phone → identity → user resolution, WhatsApp-specific rate limits and
quotas, voice transcription, a couple of deterministic commands the web
UI doesn't have ("mandame la factura …", "olvidar contexto"), and a
channel-specific text formatter for replies. It never re-implements what
an action does.

## Provider abstraction

`app/whatsapp/provider_base.py` defines `WhatsAppProvider`:

```python
class WhatsAppProvider(ABC):
    def get_connection_status(self) -> WhatsAppConnectionStatus: ...
    def request_qr_code(self) -> WhatsAppQrCode: ...
    def send_text_message(self, phone_number: str, text: str) -> None: ...
    def send_document(self, phone_number: str, filename: str, content: bytes, mime_type: str) -> None: ...
    def reconnect(self) -> None: ...
    def disconnect(self) -> None: ...
    def delete_session(self) -> None: ...
```

Two implementations ship today:

- `NullWhatsAppProvider` — always reports `disconnected`, raises
  `WhatsAppNotConfiguredError` on every mutating call. Selected whenever
  `WHATSAPP_ENABLED=false` (the default) or `WHATSAPP_PROVIDER` isn't
  `bridge`. This is why the app "starts and functions normally" with
  WhatsApp off: every caller goes through this same interface either way.
- `BridgeWhatsAppProvider` — a thin, signed HTTP client for the separate
  Node bridge. Selected when `WHATSAPP_ENABLED=true`,
  `WHATSAPP_PROVIDER=bridge`, and both `WHATSAPP_BRIDGE_URL` and
  `WHATSAPP_BRIDGE_SECRET` are set — see `provider_factory.py`.

`app/whatsapp/provider_factory.py` mirrors `app/ai/factory.py`'s existing
shape exactly (a resolver function, never a FastAPI `Depends`, "optional
infrastructure" contract). It also exposes
`is_whatsapp_transport_enabled()` / `is_whatsapp_transport_configured()`
so Settings → WhatsApp can show three distinct states — **disabled**,
**enabled but unconfigured**, and **connected/disconnected** — instead of
collapsing them into one boolean.

The Node side mirrors this with its own `WhatsAppProvider` TypeScript
interface (`whatsapp-bridge/src/provider/WhatsAppProvider.ts`):
`NullWhatsAppProvider` (a local-dev/testing escape hatch, selected via
`WHATSAPP_BRIDGE_PROVIDER=null`) and `WebJsWhatsAppProvider` (the real
`whatsapp-web.js`-backed implementation, the default).

## Bridge ↔ backend flow

1. **Inbound** (WhatsApp → app): the bridge receives a message from
   `whatsapp-web.js`, normalizes it into one envelope shape
   (`whatsapp-bridge/src/transport/inbound-handler.ts`), signs it, and
   `POST`s it to `POST /whatsapp/bridge/inbound` on the backend
   (`app/routers/whatsapp_bridge.py` — no user auth on this route, only
   the HMAC signature; see [Security model](#security-model)).
2. **Outbound** (app → WhatsApp): when the backend needs to send a reply,
   a document, or a control instruction (reconnect, disconnect, delete
   session, request a QR code), `BridgeWhatsAppProvider` signs and
   `POST`s/`GET`s to the bridge's own small HTTP surface
   (`whatsapp-bridge/src/transport/outbound-handler.ts`): `GET /status`,
   `POST /qr`, `POST /send/text`, `POST /send/document`,
   `POST /reconnect`, `POST /disconnect`, `POST /session/delete`. Every
   one of these routes requires the same HMAC signature.
3. **Health**: `GET /health` (always 200, unauthenticated liveness) and
   `GET /ready` (200 only while the provider can report its own status)
   — `whatsapp-bridge/src/health/routes.ts`.

The normalized inbound envelope:

```json
{
  "provider": "webjs",
  "message_id": "...",
  "phone_number": "...",
  "timestamp": "...",
  "type": "text | audio",
  "text": "...",
  "media": { "mime_type": "...", "size_bytes": 0 }
}
```

`provider` is echoed on every outbound instruction too, so a second,
future transport can coexist without the backend ever guessing which one
is live.

## Security model

There is no user login on the bridge↔backend boundary — it's
service-to-service, authenticated the same way this app's Stripe webhook
already is (`app/billing/stripe_provider.py._verify_signature` /
`app/webhook_signing.py`), reused deliberately rather than inventing a
second signing scheme:

- **HMAC-SHA256 over the raw request body**, with a `t=<unix_ts>,v1=<hex>`
  header (`X-WhatsApp-Bridge-Signature` on the Python side,
  `x-whatsapp-bridge-signature` on the Node side — HTTP header names are
  case-insensitive).
- **Constant-time comparison** (`hmac.compare_digest` /
  `crypto.timingSafeEqual`), never `==`.
- **Timestamp tolerance** (`WHATSAPP_SIGNATURE_TOLERANCE_SECONDS`,
  default 300s) — a signed request older than this is rejected as a
  possible replay, matching Stripe's own reference tolerance.
- **Multi-secret support** built into the signing scheme (`v1=` can
  appear more than once) for secret rotation without downtime, exactly
  like the Stripe implementation.
- **Persistent inbound idempotency**: every inbound message's
  `(provider, message_id)` is recorded in `WhatsAppInboundMessage` with a
  unique constraint — a duplicate delivery (WhatsApp itself can redeliver)
  is detected and never re-executed.
- **Request-size limits**: the bridge's inbound webhook caps the request
  body at 8MB; the bridge's own Express app caps JSON bodies at 16MB.
- **Explicit timeouts** everywhere: `WHATSAPP_REQUEST_TIMEOUT_SECONDS` on
  the Python→bridge side, `BACKEND_REQUEST_TIMEOUT_SECONDS` on the
  bridge→Python side. A hung or unreachable bridge can never hang a
  FastAPI worker thread indefinitely, and the rest of the app keeps
  working normally if the bridge is down.
- **Sanitized errors**: neither side ever logs the shared secret, and a
  failed bridge call surfaces only as one of `whatsapp_not_configured` /
  `whatsapp_bridge_unavailable` / `whatsapp_provider_error` — never a raw
  exception string, which could otherwise leak the bridge's internal URL
  or other detail.

## Identity linking

A phone number alone is never trusted as authentication. `WhatsAppIdentity`
(`app/models.py`) links a phone number to one specific `User`, scoped to
one organization:

```
WhatsAppIdentity
  id, provider, organization_id, user_id, normalized_phone_number
  status: pending | verified | disabled
  verification_code_hash, verification_expires_at, verification_attempts
  verified_at, last_message_at, created_at, updated_at
```

`(provider, normalized_phone_number)` is globally unique — deliberately,
not per-organization. This experimental phase runs **exactly one shared
WhatsApp Web session for the whole deployment** (one `WHATSAPP_BRIDGE_URL`
/ `WHATSAPP_BRIDGE_SECRET` pair, matching the spec's own "enable only on
Enterprise or an internal demo plan" framing), so one phone number can
only ever mean one (organization, user) pair across the entire deployment
— never silently different users depending on which organization asks.

**Linking flow** (Settings → WhatsApp → "Your WhatsApp number"):

1. The user enters their phone number and submits it
   (`POST .../whatsapp/link`). This already re-checks `require_whatsapp`
   (the plan gate) and the organization's `max_whatsapp_users` quota
   before creating anything.
2. The backend creates a `pending` `WhatsAppIdentity`, generates a
   short-lived one-time numeric code, and returns the **raw** code to the
   caller **exactly once** in the HTTP response — only its SHA-256 hash
   (`verification_code_hash`) is ever persisted. This mirrors the existing
   API-key create/rotate contract ("only ever returned once").
3. The user sends that code as a WhatsApp message to the connected
   number. The bridge forwards it inbound like any other message;
   `app/whatsapp/service.py._try_handle_verification_code` matches it
   against the pending identity for that phone, marks it `verified`, and
   replies with a confirmation.
4. Wrong codes increment `verification_attempts`;
   `WHATSAPP_MAX_VERIFICATION_ATTEMPTS` (default 5) permanently locks out
   even a later-correct code, forcing a fresh link request. Codes expire
   after `WHATSAPP_VERIFICATION_CODE_TTL_MINUTES` (default 10).
5. A phone already verified to a *different* user or organization cannot
   be linked again until it's revoked from wherever it currently lives.

**Every inbound command re-derives identity from scratch** — active user,
active membership, active organization — on every single message
(`app/whatsapp/queries.is_user_active_member`), never from a cache. A
removed user or a deactivated membership loses WhatsApp access
immediately, on the very next message, exactly like it would on the web.

Users can unlink their own number at any time
(`POST .../whatsapp/me/revoke`); an owner/admin (`settings.manage`) can
revoke *any* organization member's mapping
(`POST .../whatsapp/identities/{id}/revoke`).

## Supported commands

**Read-only** (answered immediately, no confirmation):

- `Ayuda` — list what the assistant can do
- `Buscar cliente …`, `Buscar producto …`, `Buscar presupuesto …`,
  `Buscar factura …`
- `Listar facturas pendientes`, `Listar facturas vencidas`
- `Consultar estado de factura …`
- `Mostrar ventas del mes`, `Mostrar ingresos del mes`,
  `Mostrar resumen del negocio`
- `Mandame la factura INV-…`, `Mandame el presupuesto QUO-…` (sends the
  existing generated PDF — see [PDF delivery](#pdf-delivery))

**Mutating** (always require `CONFIRMAR`/`CANCELAR` — see below):

- `Crear presupuesto`, `Crear factura`
- `Marcar factura como pagada`
- `Enviar presupuesto`, `Enviar factura`

Example messages:

> "Creá una factura para Juan Pérez por USD 1.200 por diseño web."
> "Mostrame las facturas vencidas."
> "¿Cuánto facturé este mes?"

Every one of these is interpreted by the same `AIProvider` + `ActionTool`
registry the web assistant uses — WhatsApp does not have its own,
separate list of recognized intents beyond the couple of deterministic,
non-AI shortcuts noted above (help, forget-context, and the
`Mandame la factura/presupuesto …` regex match, which is answered
without spending an AI call at all).

> **Note (found during Phase 23.1's live verification against a real AI
> provider):** `TOOL_REGISTRY` (`app/ai/tools/registry.py`) only contains
> invoice/quote tools — there is no `create_customer` or `create_product`
> tool. This is a pre-existing gap in the underlying AI Business
> Assistant, not something WhatsApp introduced: asking the **web**
> assistant to "Creá un cliente…" gets the identical "I can't create
> customer profiles" reply, proving WhatsApp faithfully inherits the same
> capabilities (and the same gaps) as the web UI, exactly as designed.
> "Crear cliente"/"Crear producto" were listed here and in the original
> phase spec as if supported; they are not, until a real
> `create_customer`/`create_product` `ActionTool` is added to the shared
> registry (a change to the core assistant, out of scope for the
> WhatsApp-specific work in this repo so far). Read-only lookups
> ("Buscar cliente …") already work today — they're answered from
> injected business context, not a tool call, so they don't depend on
> this gap.

## Confirmation flow

Every mutating or financially relevant action goes through the same
propose → confirm/cancel lifecycle the web assistant already uses
(`AssistantAction`, `app/services/assistant_actions.py`) — WhatsApp is
just a different channel presenting the same pending action.

```
User:  "Creá una factura para Juan Pérez por USD 1.200 por diseño web."

Bot:   Voy a crear esta factura:

       Cliente: Juan Pérez
       Concepto: Diseño web
       Total: USD 1.200
       Estado: Pendiente

       Respondé CONFIRMAR para continuar o CANCELAR para detener la operación.
```

- The pending proposal is scoped to **organization + user + phone** — a
  different phone number, even a verified one belonging to a different
  user in the same organization, cannot confirm someone else's proposal.
- Proposals expire quickly (`ASSISTANT_ACTION_TTL_SECONDS`, the same
  constant the web UI uses).
- Permission and plan/quota limits are **re-checked at confirmation
  time**, not just when the proposal was created — an action proposed
  while allowed can still be correctly rejected if something changed in
  between (a downgrade, a revoked permission, a quota that filled up).
- A second `CONFIRMAR` on an already-executed proposal fails cleanly
  (`no_pending_action`) — it can never execute twice.
- `CANCELAR` is idempotent.
- An ambiguous reference (e.g. two customers both plausibly named "Juan")
  never silently picks one — the assistant asks for clarification instead
  of creating a proposal at all.

## Conversation context

Short-lived context lets a user say "Creá un cliente llamado Juan Pérez."
and then, in a later message, "Ahora hacé una factura para él por 500
dólares." — scoped to **organization + user + phone**,
`WHATSAPP_CONTEXT_TTL_MINUTES` (default 15) and
`WHATSAPP_CONTEXT_MAX_MESSAGES` (default 10) bound how long/how much of it
is kept. Say `olvidar contexto` at any time to reset it explicitly.

This context is held **in-process, in memory**
(`app/whatsapp/context_store.py`) — deliberately not a database table.
Two reasons:

1. **Minimal retention** — the spec calls for genuinely short-lived,
   minimal-footprint context, not another durable table of
   (paraphrased) user messages.
2. It mirrors `app/rate_limit.py`'s own existing single-process
   assumption for this deployment shape (a single web process; no
   horizontally-scaled worker pool sharing this state).

The real consequence of that choice: AI interpretation for a WhatsApp
message must run **synchronously, inside the inbound webhook request**,
in the same process that holds the context — not as a background job.
A separate job-worker process wouldn't share this in-memory dictionary.
This is a deliberate, documented trade-off, not an oversight — see
["Background jobs"](#background-jobs) below for what *is* genuinely
handled by the job queue.

Context never bypasses confirmation — it can carry forward *which*
customer "him" refers to, but a mutating action built from that context
still goes through the exact same propose/confirm flow as any other.

## Voice messages

```
WhatsApp voice note
  → bridge downloads media, base64-encodes it into the inbound envelope
  → backend validates size / MIME / (declared) duration BEFORE decoding
  → TranscriptionProvider.transcribe(...)
  → normalized text
  → the SAME assistant/action pipeline as a typed message
  → transcript sent back to the user
  → confirmation flow if it was a mutation
  → reply
```

- Size is checked from the envelope's declared `size_bytes` **before**
  the base64 payload is ever decoded into memory
  (`WHATSAPP_AUDIO_MAX_BYTES`, default 5MB) — an oversized declared size
  is rejected without ever allocating the full decoded buffer.
- MIME type is checked against a closed allow-list
  (`audio/ogg`, `audio/ogg; codecs=opus`, `audio/mpeg`, `audio/mp4`,
  `audio/aac`, `audio/amr` — WhatsApp's own common voice-note format is
  Opus-in-Ogg) — an unrecognized type is rejected outright, never passed
  through to a transcription provider blind.
- Media is only ever held in memory for the duration of one request —
  never written to persistent storage, never retained by default.
- If no transcription provider is configured, the user gets an honest
  "voice messages aren't available right now" reply — never a silent
  failure or a fabricated transcript.
- The transcript is sent back to the user **before** any confirmation
  prompt, so they can see exactly what the assistant understood.

### `TranscriptionProvider` abstraction

`app/transcription/` mirrors `app/ai/base.py` + `app/ai/factory.py`'s
existing shape:

- `TranscriptionProvider` (ABC) — `transcribe(audio_bytes, mime_type) -> str`
- `NullTranscriptionProvider` — always raises
  `TranscriptionNotConfiguredError` (the default; this is what produces
  the honest "not configured" reply above)
- `FakeTranscriptionProvider` — deterministic, test-only, never
  selectable when `ENVIRONMENT=production`

**No real vendor adapter ships in this phase.** Neither of this app's
existing AI providers (`app/ai/anthropic_provider.py`,
`app/ai/gemini_provider.py`, both built against `app/ai/base.py`'s
`AIProvider` interface) can currently accept raw audio input without
widening that core, already-in-production interface — and the spec itself
only calls for a real adapter "if an existing provider/API can support it
cleanly." Adding one would mean either a third-party STT-only vendor (a
real, separate integration decision, out of scope here) or extending
`AIProvider` itself for one experimental feature, which risks destabilizing
the one interface every other AI-driven part of the app already depends
on. Wiring a real transcription vendor in is a natural, contained next
step (see [Roadmap](#migration-path-to-the-meta-cloud-api) framing below)
— today the abstraction is real and tested, the vendor behind it is not.

## PDF delivery

`Mandame la factura INV-000145.` / `Mandame el presupuesto QUO-000120.`:

1. A deterministic regex match (`\b(INV|QUO)-?0*(\d+)\b` — no AI call
   spent on this) resolves the document reference.
2. Existing permission and **tenant-ownership** checks run — the document
   must belong to the caller's own organization; a document ID from
   another tenant is never resolved, even if it happens to be guessable.
3. The **existing** PDF renderers are reused unchanged —
   `app/invoice_pdf.py::render_invoice_pdf`,
   `app/quote_pdf.py::render_quote_pdf` — there is no WhatsApp-specific
   PDF generation.
4. Sending happens through a background job
   (`JobType.whatsapp_send_document`,
   `app/jobs/handlers/whatsapp.py::handle_whatsapp_send_document`), which
   re-renders the PDF from the document's ID (stateless — no dependency
   on the in-process conversation context) and calls
   `WhatsAppProvider.send_document(...)`. This is genuinely queued rather
   than synchronous, unlike AI interpretation above, precisely because it
   has no in-memory-state dependency to worry about.
5. The filename sent is a safe, generated one (never a raw filesystem
   path or internal storage URL); a missing/not-found document replies
   honestly without leaking the raw reference the user typed.
6. Retry classification: an unconfigured bridge fails the job
   permanently (retrying wouldn't help); a bridge that's merely
   unreachable right now is retried.

## Response presentation

WhatsApp replies are generated by a small, channel-specific formatter
(inside `app/whatsapp/service.py`), kept separate from the business logic
that decided *what* happened — mobile-friendly, no raw JSON, no stack
traces, no internal database IDs, no sensitive data, and in the
organization's configured language when available:

```
✅ *Factura creada*

Número: INV-000145
Cliente: Juan Pérez
Total: USD 1.200
Estado: Pendiente
```

## Permissions

| Action | Who |
| --- | --- |
| Link / unlink **your own** phone number | Any active organization member |
| View your own linked number's status | Any active organization member |
| View every organization member's linked number, revoke *any* mapping, view command history, request a QR code, reconnect/disconnect/delete the session | `settings.manage` (owner/admin) only |
| Send/receive actual WhatsApp commands | Requires a `verified` `WhatsAppIdentity` **and** every ordinary permission check the equivalent web action would require (RBAC, plan feature, plan limit, AI quota, tenant isolation) |

Session files, the bridge's internal QR payload aside from the image
itself, and the linking verification code (after its one-time response)
are never exposed anywhere in the API or the frontend.

## Plans and quotas

Four new fields on `Plan` (`app/models.py`), enforced through the
existing entitlements/capabilities/enforcement architecture — no
WhatsApp-specific enforcement mechanism was built:

| Field | Meaning |
| --- | --- |
| `whatsapp_enabled` | All-or-nothing feature gate (`app.billing.enforcement.require_whatsapp`), same shape as the existing AI/Analytics gates. |
| `voice_messages_enabled` | Separate gate for voice notes specifically (`require_whatsapp_voice_messages`) — a plan can allow text commands without voice. |
| `max_whatsapp_users` | How many verified `WhatsAppIdentity` rows an organization may have at once (`NULL` = unlimited). |
| `monthly_whatsapp_actions` | How many WhatsApp-originated actions may be processed per calendar month (`NULL` = unlimited). Counted the same way every other plan-limited resource is (`app/services/plan_limits.py`), atomically. |

For this experimental phase, only the seeded **Enterprise** plan enables
WhatsApp (`max_whatsapp_users=5`, `monthly_whatsapp_actions=200`,
`voice_messages_enabled=true`) — every other seeded plan leaves it off.
Settings → WhatsApp distinguishes three independent reasons the feature
might be unusable: **transport disabled** (`WHATSAPP_ENABLED=false`),
**transport enabled but unconfigured** (bridge URL/secret missing), and
**plan restricted** — never collapsed into one generic error.

## Rate limiting and abuse control

Built on the existing `app/rate_limit.py` conventions (same
`RateLimitRule`/`enforce_rate_limit` shape used everywhere else in the
app), scoped by phone, user, organization, and message ID as
appropriate: inbound message floods, repeated `CONFIRMAR`/`CANCELAR`
attempts, verification-code attempts, QR requests, and oversized/invalid
media are all bounded. Duplicate message delivery is additionally caught
by the persistent `(provider, message_id)` idempotency check described
under [Security model](#security-model), independent of rate limiting.

## Event, audit, and background jobs

Successful mutations go through the exact same service-layer functions
the web UI calls, so they **naturally** emit the same notifications,
audit entries, webhooks, and email jobs — this phase does not create a
second, parallel notification/event path (`app/notifications/service.py`'s
`emit_event` remains the single fan-out entry point, unmodified).

Instead, a new `WhatsAppInboundMessage` table records **safe channel
metadata only** — provider, inbound message ID, message type (text/audio),
resolved command/action type, status, failure code, timestamp — and is
what Settings → WhatsApp's "Recent activity" table reads from. It
deliberately never stores raw message text, transcripts, phone numbers
tied to content, or anything else that would turn "activity metadata"
into a message log.

Only one operation genuinely runs as a background job:
`JobType.whatsapp_send_document` (PDF delivery — see
[PDF delivery](#pdf-delivery) above), because it's the one WhatsApp
operation with no dependency on the in-process conversation-context state
described in [Conversation context](#conversation-context). Transcription
and AI interpretation run synchronously within the inbound webhook
request for the reason explained there.

## Bridge reliability

- `GET /health` — always 200, unauthenticated, pure liveness.
- `GET /ready` — 200 only while the provider can report a connection
  status without throwing.
- Explicit connection states: `disconnected`, `connecting`,
  `qr_required`, `connected`, `session_expired`.
- **Bounded** reconnect backoff (`RECONNECT_INITIAL_DELAY_SECONDS`,
  `RECONNECT_MAX_DELAY_SECONDS`, `RECONNECT_MAX_ATTEMPTS`) — never an
  infinite retry loop.
- Graceful shutdown on `SIGTERM`/`SIGINT`: the HTTP server stops
  accepting new requests and the WhatsApp client is torn down cleanly
  before the process exits.
- If `whatsapp-web.js` itself breaks (a WhatsApp Web markup/API change is
  the classic failure mode for this kind of library), the bridge reports
  `session_expired`/error states rather than crashing silently, and the
  rest of the SaaS is entirely unaffected — every backend code path
  behind `WhatsAppProvider` already treats the bridge as something that
  can be down at any time.

## Session persistence

WhatsApp Web session data (`whatsapp-web.js`'s `LocalAuth`) is
**equivalent to full access to the connected WhatsApp account** — anyone
who obtains it can act as that phone number without ever scanning a QR
code again.

- Persisted only under `WHATSAPP_SESSION_PATH`, which must be a
  dedicated, persistent volume in any real deployment — see the
  `whatsapp_session` named volume in `docker-compose.yml`.
- Already gitignored inside `whatsapp-bridge/.gitignore`
  (`.wwebjs_auth/`, `.wwebjs_cache/`, `session/`, `sessions/`) — never
  committed, regardless of the configured path.
- Never exposed to the frontend or through any API response — the
  Settings → WhatsApp UI shows connection *status*, never session
  contents.
- "Delete session" (Settings → WhatsApp, `settings.manage` only, or
  deleting the `whatsapp_session` Docker volume) is explicit and
  irreversible — the next connection always starts from a fresh QR scan.
- **Back this volume up like a credential, not like ordinary data** — if
  you back it up at all, encrypt it, and treat a leak of it as equivalent
  to a leaked password for that WhatsApp account.

## Docker / deployment

The bridge is an **optional**, disabled-by-default Compose service (see
`docker-compose.yml`'s `whatsapp-bridge` service, under the `whatsapp`
Compose profile):

```bash
# WhatsApp is NOT started by a bare docker compose up.
docker compose up --build

# To try it locally: set WHATSAPP_ENABLED, WHATSAPP_PROVIDER=bridge, and a
# real WHATSAPP_BRIDGE_SECRET (see .env.docker.example), then:
docker compose --profile whatsapp up --build
```

The bridge:

- needs a **persistent, long-running process** — not a request-scoped
  serverless function, since it holds an open WhatsApp Web connection;
- needs a **real Chromium browser runtime** — `whatsapp-bridge/Dockerfile`
  installs Debian's own `chromium` package and points Puppeteer at it
  (`PUPPETEER_SKIP_CHROMIUM_DOWNLOAD=true`,
  `PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium`) rather than relying on
  Puppeteer's bundled Chromium download, so the image's installed shared
  libraries and its browser binary always match;
- needs a **persistent volume** for `WHATSAPP_SESSION_PATH` (the
  `whatsapp_session` named volume) — without one, every container restart
  forces a fresh QR scan;
- has its own `HEALTHCHECK` (`GET /health`) and depends on the `backend`
  service being healthy first (startup ordering), matching this repo's
  existing `worker` service's own `depends_on` shape.

**This is not enabled on the existing Render/Vercel deployment**, and
should not be. Render's free web-service tier (and Vercel generally) is
serverless-shaped and cannot host a persistent Chromium process or a
persistent session volume — the same limitation that already means this
repo's `worker` service (background jobs) isn't provisioned there either.
Running the bridge for real requires a host that gives you a genuinely
long-running container with a persistent disk (a Render *Background
Worker* or *Private Service* with a persistent disk, a small VPS, Fly.io,
Railway, etc.) — not a checkbox this repository's one-click deploy paths
turn on for you.

## Troubleshooting

| Symptom | Likely cause |
| --- | --- |
| Settings → WhatsApp shows "transport disabled" | `WHATSAPP_ENABLED` is unset/false. This is the default — set it to `true` and configure the bridge to change it. |
| Shows "enabled but unconfigured" | `WHATSAPP_PROVIDER` isn't `bridge`, or `WHATSAPP_BRIDGE_URL`/`WHATSAPP_BRIDGE_SECRET` is missing. |
| Shows "plan restricted" | The organization's current plan doesn't have `whatsapp_enabled` — only the seeded Enterprise plan does by default. |
| QR code won't scan / expires | QR codes rotate roughly every 60s; request a fresh one from Settings → WhatsApp. |
| Stuck on "Connecting" | The bridge process may be mid-restart; wait and retry, or check the bridge's own logs/`GET /health`. |
| "Session expired" | WhatsApp itself signed the linked phone out remotely (common after a long disconnect, or the linked phone's own "Linked Devices" list being cleared) — delete the session and reconnect with a fresh QR scan. |
| A message gets no reply at all | Confirm the sending phone number shows `Verified` (not `Pending`) in Settings → WhatsApp, and that the organization's plan includes WhatsApp. |
| Voice notes always fail | No `TranscriptionProvider` is configured — this is an honest, expected failure today (see [Voice messages](#voice-messages)), not a bug to chase. |

## Unofficial WhatsApp risks

Read this before connecting a real phone number to anything but a
disposable test account:

- **`whatsapp-web.js` is not an official WhatsApp integration.** It works
  by automating the WhatsApp Web client the same way a real browser tab
  would, not through WhatsApp's own published API.
- **WhatsApp's Terms of Service do not authorize this kind of automation
  for a real business account.** Using it carries a genuine risk of the
  connected number being temporarily or permanently restricted by
  WhatsApp, entirely outside this application's control.
- **It can break without warning.** WhatsApp Web's own client markup/
  protocol changes periodically; `whatsapp-web.js` (an open-source,
  community-maintained project) sometimes lags behind those changes,
  which can break connectivity until the library itself is updated.
- **Session data is equivalent to account access** — see
  [Session persistence](#session-persistence) above.
- **Do not use a phone number tied to a real business, real customers, or
  a number you cannot afford to lose.** Use a disposable/test number for
  any demo or evaluation of this feature.

## Migration path to the Meta Cloud API

This feature was deliberately built so the *unofficial* transport is a
swappable implementation detail, not something baked into the business
logic:

1. **Nothing above `WhatsAppProvider` (`app/whatsapp/provider_base.py`)
   changes.** `app/whatsapp/service.py`, the identity-linking flow, the
   confirmation/context/quota logic, and every router already depend only
   on that interface — never on `whatsapp-web.js` or the bridge's HTTP
   contract directly.
2. Add a new concrete provider — e.g. `CloudApiWhatsAppProvider`
   (`app/whatsapp/cloud_api_provider.py`) — implementing
   `get_connection_status` / `send_text_message` / `send_document` / etc.
   against Meta's actual Graph API endpoints and its own webhook
   verification scheme (a `hub.verify_token` handshake plus its own
   payload-signature header, in place of the bridge's shared-secret HMAC).
3. Add a new inbound webhook route (Meta posts directly to your backend —
   there is no separate Node bridge process needed at all for this path,
   since Meta's Cloud API is a hosted HTTP service, not a browser
   automation you have to run yourself).
4. Extend `provider_factory.get_whatsapp_provider()` to select between
   `bridge` (this experimental phase) and a new `cloud_api` value for
   `WHATSAPP_PROVIDER`.
5. The entire `whatsapp-bridge/` Node service, its Docker service, its
   session-volume requirements, and the "unofficial risk" warnings all
   become optional/removable at that point — the Cloud API needs none of
   them, since it isn't automating a browser.
6. Everything documented above the transport layer in this document —
   identity linking, confirmation flow, context, plans/quotas, audit,
   permissions — stays exactly as-is; only ["Architecture"](#architecture),
   ["Bridge ↔ backend flow"](#bridge--backend-flow), and
   ["Security model"](#security-model) would need a second section for
   the new transport.

**This phase does not implement the Meta Cloud API itself** — the above
is the intended path, not a claim that any of it exists yet.
