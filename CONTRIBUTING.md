# Contributing

Thanks for your interest in improving this project. This is a short guide,
not a bureaucracy — read it once and you're set.

## Branching

- Branch from `main`. Use a short, descriptive name: `feature/quote-pdf-notes`,
  `fix/invoice-due-date-timezone`.
- Keep branches focused on one change. Unrelated fixes belong in their own PR.

## Running tests locally

There's no CI yet (see the [Roadmap](README.md#roadmap)), so running these
yourself before opening a PR is what stands in for it:

```bash
# Backend
pytest

# Frontend
cd frontend
npm test
npx tsc --noEmit
npm run build
```

All four should pass before you open a PR.

## Code style & conventions

- **Every new backend route must be permission-checked.** Call
  `require_permission(...)` for anything beyond a low-sensitivity read (see
  `app/permissions.py` and the existing routers for the pattern). Never gate
  access on a role name directly — add or reuse a `Permission` value instead.
- **Frontend UI gating goes through `hasPermission()`**, never a
  `role === "owner"`-style check. See `frontend/lib/permissions.ts`.
- **Translation keys are added in pairs.** Every new user-facing string needs
  both an English and a Spanish entry in `frontend/lib/i18n/translations.ts` —
  never just one.
- Match the surrounding file's existing patterns (naming, error handling,
  test structure) rather than introducing a new convention for one change.
- No unrelated refactors bundled into a feature or fix PR — open a separate
  PR for cleanup.

## Pull requests

- Keep PRs small and focused; it's easier to review and easier to revert.
- Describe *why* the change is needed, not just what it does — the diff
  already shows what changed.
- Add or update tests for any behavior change.
- Note any manual verification you did (e.g. "checked in the browser at
  desktop and mobile widths") if the change is UI-facing.
