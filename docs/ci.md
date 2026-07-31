# CI (Phase P2.1)

`.github/workflows/ci.yml` runs on every pull request and every push to
`main`, as two independent, merge-blocking jobs. It does not deploy
anything (see `render.yaml` for that) and does not run `npm audit` or
`pip-audit` -- neither has a documented policy in this repo yet, so
neither is wired up as a blocking gate. It does not modify
`.github/workflows/send-invoice-reminders.yml` (the existing cron job),
which keeps running exactly as before.

## Reproducing CI locally

**Backend** (from the repo root):

```bash
pip install -r requirements-test.txt
python -m pytest -q
```

No environment variables need to be set by hand -- `tests/conftest.py`
sets `DATABASE_URL` (a throwaway SQLite tempfile), `JWT_SECRET_KEY`, and
`ENVIRONMENT=development` itself, before any `app.*` module is imported.

**Frontend** (from `frontend/`):

```bash
npm ci
npx tsc --noEmit
npm test
npm run build
```

`npm ci` requires the committed `frontend/package-lock.json` and installs
exactly what it pins -- if you've added a dependency, run `npm install`
locally first so the lockfile is up to date, then commit both files.

## Why two jobs, not one

A frontend-only change doesn't need to wait on backend dependency
installation, and vice versa -- GitHub also renders each job as its own
required-check entry, so a failure is immediately attributable to
"backend" or "frontend" without opening the log.
