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

| Variable                      | Default                        | Notes                                                                 |
| ------------------------------ | ------------------------------- | ---------------------------------------------------------------------- |
| `DATABASE_URL`                 | `sqlite:///./invoices.db`       | See [Database](#database) below.                                       |
| `JWT_SECRET_KEY`                | insecure dev default (warns)    | Set to a real secret before deploying. Generate with `python -c "import secrets; print(secrets.token_urlsafe(48))"`. |
| `ACCESS_TOKEN_EXPIRE_MINUTES`   | `1440` (24h)                    | JWT access token lifetime.                                              |

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
