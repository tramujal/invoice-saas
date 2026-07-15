# Invoicing SaaS

A small multi-tenant invoicing app: FastAPI + SQLAlchemy backend, Next.js frontend.

## Architecture

- **Backend** (`app/`) — FastAPI, SQLAlchemy 2.0 ORM, JWT authentication. Every
  resource is scoped to an `Organization`; `require_org_member` gates access
  on every request.
- **Frontend** (`frontend/`) — Next.js 14 App Router, Tailwind CSS. Talks to
  the backend over a configurable API base URL, stored client-side alongside
  the auth session.

## Backend setup

```bash
pip install -r requirements.txt
cp .env.example .env   # then edit .env — at minimum set JWT_SECRET_KEY
python -m app.seed_demo   # optional: creates a demo login (see printed credentials)
uvicorn app.main:app --reload
```

The API listens on `http://127.0.0.1:8000` by default; interactive docs are at
`/docs`.

### Environment variables

| Variable                     | Default                                          | Notes                                                                                                                                          |
| ----------------------------- | -------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| `DATABASE_URL`                | `sqlite:///./invoices.db`                        | See [Database](#database) below.                                                                                                               |
| `JWT_SECRET_KEY`              | insecure dev default (warns)                     | Generate with `python -c "import secrets; print(secrets.token_urlsafe(48))"`. **Required** — the app refuses to start if `ENVIRONMENT=production` and this is unset. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `1440` (24h)                                     | JWT access token lifetime.                                                                                                                      |
| `ENVIRONMENT`                | `development`                                    | Set to `production` when deploying — this is what enforces `JWT_SECRET_KEY` above.                                                             |
| `CORS_ALLOWED_ORIGINS`        | `http://localhost:3000,http://127.0.0.1:3000`    | Comma-separated list of frontend origins allowed to call the API. Set to your deployed frontend URL(s) in production.                          |
| `AI_PROVIDER`                 | `anthropic`                                      | Which AI provider backs `POST .../assistant/chat` — `anthropic` or `gemini`. Unknown values return a clean 503. See [AI Business Assistant](#ai-business-assistant) below. |
| `ANTHROPIC_API_KEY`           | unset (assistant returns 503)                    | Required only when `AI_PROVIDER=anthropic`. Optional — everything else in the app works without it.                                             |
| `GEMINI_API_KEY`              | unset (assistant returns 503)                    | Required only when `AI_PROVIDER=gemini`. Optional — everything else in the app works without it.                                                |
| `AI_MODEL`                    | dev-only fallback (`claude-sonnet-5` / `gemini-2.5-flash`, per provider); **required** if `ENVIRONMENT=production` | The model id to call, for whichever provider is selected. Never silently assumed in production — see `app/ai/factory.py`. |
| `AI_MAX_OUTPUT_TOKENS`, `AI_REQUEST_TIMEOUT_SECONDS`, `AI_MAX_USER_MESSAGE_LENGTH`, `AI_MAX_HISTORY_MESSAGES`, `AI_MAX_HISTORY_MESSAGE_LENGTH`, `AI_MAX_HISTORY_TOTAL_CHARS`, `AI_MAX_CONTEXT_CHARS` | conservative defaults, see `.env.example` | Cost/abuse controls for the assistant. Provider-agnostic — apply the same regardless of `AI_PROVIDER`. Rarely need changing. |

#### AI Business Assistant

The assistant (`POST .../assistant/chat`, surfaced at `/assistant` in the
frontend) is built behind a small provider abstraction
(`app/ai/base.py`'s `AIProvider`) so the router, rate limiting, business
context, and frontend never know or care which underlying AI API is
actually being called:

- `app/ai/anthropic_provider.py` — calls Anthropic's Messages API directly
  over HTTP.
- `app/ai/gemini_provider.py` — calls Google's Gemini API via the official
  `google-genai` SDK, adapting its generator-based streaming to the same
  `Iterator[str]` interface the router expects.
- `app/ai/factory.py` — reads `AI_PROVIDER` and returns the matching
  implementation, requiring only that provider's own API key.

Switching providers is a config-only change: set `AI_PROVIDER=gemini` and
`GEMINI_API_KEY` (leaving `ANTHROPIC_API_KEY` untouched, or vice versa) —
no code, router, or frontend changes needed. An unset or unrecognized
`AI_PROVIDER` value returns a clean 503 with a message naming the valid
options, the same way a missing API key does.

### Production start commands

```bash
# Backend — bind to 0.0.0.0 and the platform-provided PORT
uvicorn app.main:app --host 0.0.0.0 --port $PORT

# Frontend
npm run build
npm start
```

### Database

The backend reads `DATABASE_URL` from the environment:

- **Unset** — falls back to a local SQLite file (`./invoices.db`), zero setup.
  Foreign key enforcement is turned on for the SQLite connection so local
  behavior (e.g. `ON DELETE CASCADE` / `SET NULL`) matches what Postgres does
  in production.
- **Set to a Postgres URL** — either `postgresql://...` or the legacy
  `postgres://...` form (as handed out by most hosting platforms) both work;
  the app rewrites the scheme to use the `psycopg` (v3) driver automatically.
  Example: `DATABASE_URL=postgresql://user:password@localhost:5432/invoices`.

Tables are created automatically on startup via
`Base.metadata.create_all()` — there is **no migration tool (Alembic) yet**.
This is fine for a fresh database, but once there's a live database with real
data that needs schema changes, Alembic (or an equivalent) will need to be
introduced — `create_all()` only adds missing tables, it never alters
existing ones.

## Frontend setup

```bash
cd frontend
npm install
cp ../.env.example .env.local   # only NEXT_PUBLIC_API_URL is used here
npm run dev
```

Runs at `http://localhost:3000`. On first load you'll land on `/login`,
where you can either sign in or create a new account (which also creates
your organization).

## Docker

An alternative to the setup above: bring up Postgres, the backend, and the
frontend together with Docker Compose — real Postgres locally instead of
SQLite, no local Python/Node install needed.

```bash
docker compose up --build
```

That's it — no `.env` file is required; `docker-compose.yml` already has
safe local defaults for everything. The frontend is at
`http://localhost:3000`, the API at `http://localhost:8000` (`/docs` for
interactive docs), and Postgres itself is published at `localhost:5432` if
you want to connect with `psql` or a GUI client.

- Data persists across `docker compose down` / `docker compose up` (named
  volume `pgdata`) — only `docker compose down -v` removes it.
- To enable real email sending or the AI Business Assistant locally, copy
  [`.env.docker.example`](.env.docker.example) to `.env` and fill in the
  keys you want, then `docker compose up --build` again. (Docker Compose
  auto-loads a root-level `.env` file for substitution — if you've also
  been using the non-Docker setup above and already have a `.env` from `cp
  .env.example .env`, that's fine: `docker-compose.yml` hardcodes its own
  database/JWT/CORS values directly rather than reading them from `.env`,
  so only the optional AI/email keys are ever picked up from it.)
- The scheduled reminder jobs (normally triggered by the GitHub Actions
  workflow in production) can be run on demand against the Dockerized
  database:
  ```bash
  docker compose run --rm backend python -m app.jobs.send_due_invoice_reminders --dry-run
  docker compose run --rm backend python -m app.jobs.send_expiring_quote_reminders --dry-run
  ```
  (`docker compose run` inherits the `backend` service's environment, so
  `DATABASE_URL` already points at the Dockerized Postgres — drop
  `--dry-run` to actually send.)
- This is purely additive — it doesn't change the Render/Vercel/Neon
  deployment below or the non-Docker setup above; use whichever fits what
  you're doing.
- Docker's own port-mapping/NAT layer means the client IP the backend's
  rate limiter sees inside the container (`request.client.host`) may not be
  literally `127.0.0.1`, even for requests from the same machine — commonly
  the `docker0` bridge gateway on Linux, or something further removed via
  the VM networking layer on Docker Desktop for Windows/Mac. This doesn't
  weaken anything (`TRUSTED_PROXY_HOPS=0` in the compose file still ignores
  `X-Forwarded-For` entirely, matching local dev), it just means don't be
  surprised if rate-limit buckets key on an unfamiliar-looking IP locally.

## Deployment

Three pieces, in order: a Postgres database (Neon), the API (Render), then
the frontend (Vercel). The last two steps have a circular dependency — the
API needs to know the frontend's URL for CORS, and the frontend needs the
API's URL — so you'll configure one, deploy the other, then come back and
fill in the blank.

### 1. Database — Neon

1. Create a project at [neon.tech](https://neon.tech) and a database inside it.
2. Copy the **pooled connection string** it gives you — it looks like
   `postgresql://user:password@ep-xxxx-pooler.region.aws.neon.tech/dbname?sslmode=require`.
3. Use it as-is for `DATABASE_URL`. The app rewrites the scheme to use the
   `psycopg` driver automatically and passes the `sslmode=require` query
   param through untouched, so no edits are needed.

Tables are created automatically the first time the API boots against this
database (`Base.metadata.create_all()` — no migration step required for a
fresh database; see the [Database](#database) note above about Alembic).

### 2. Backend — Render

**Option A — Blueprint:** In the Render dashboard, "New +" → "Blueprint",
point it at this repo. Render reads [`render.yaml`](render.yaml) and creates
the web service with the correct build/start commands already filled in.

**Option B — Manual web service:**
- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`

Either way, set these environment variables in the Render dashboard:

| Variable                  | Value                                                        |
| -------------------------- | ------------------------------------------------------------- |
| `DATABASE_URL`             | the Neon connection string from step 1                        |
| `JWT_SECRET_KEY`           | output of `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `ENVIRONMENT`              | `production`                                                   |
| `CORS_ALLOWED_ORIGINS`     | leave a placeholder for now (e.g. `https://placeholder.vercel.app`) — you'll update this in step 4 |

Deploy, then note the Render URL (e.g. `https://invoicing-api.onrender.com`) —
you'll need it for the frontend.

Optionally, set `AI_PROVIDER` plus that provider's API key and `AI_MODEL` to
enable the AI Business Assistant (`/assistant` in the frontend) — either
`AI_PROVIDER=anthropic` with `ANTHROPIC_API_KEY`, or `AI_PROVIDER=gemini`
with `GEMINI_API_KEY`. All of these are left blank in
[`render.yaml`](render.yaml) for you to fill in from the dashboard; without
them the assistant page just shows a "not configured" message and nothing
else in the app is affected. See [AI Business Assistant](#ai-business-assistant)
above for how the provider abstraction works.

### 3. Frontend — Vercel

1. Import this repo into Vercel.
2. In the project's settings, set **Root Directory** to `frontend` — this is
   a monorepo, and Vercel won't find the Next.js app without this.
3. Set the environment variable `NEXT_PUBLIC_API_URL` to the Render URL from
   step 2 (e.g. `https://invoicing-api.onrender.com`).
4. Deploy, then note the Vercel URL (e.g. `https://your-app.vercel.app`).

### 4. Close the loop

Back in Render, update `CORS_ALLOWED_ORIGINS` to the real Vercel URL from
step 3 (comma-separate multiple values if you also want to allow preview
deployments), and redeploy the backend.

At this point: Vercel → Render is wired via `NEXT_PUBLIC_API_URL`, and
Render → Vercel is wired via `CORS_ALLOWED_ORIGINS`. Sign in at your Vercel
URL to confirm everything connects end to end.
