## Summary

What does this PR do, and why? (The diff already shows *what* changed —
focus this on *why* it's needed.)

## Type of change

- [ ] Bug fix
- [ ] New feature
- [ ] Refactor / cleanup (no behavior change)
- [ ] Documentation
- [ ] CI / tooling

## Checklist

- [ ] Backend: `pytest` passes locally
- [ ] Frontend: `npm test`, `npx tsc --noEmit`, and `npm run build` all
      pass locally
- [ ] New/changed behavior has test coverage
- [ ] Every new organization-scoped route calls `require_permission(...)`
      (never gates access on a role name directly) — see
      [`CONTRIBUTING.md`](../CONTRIBUTING.md)
- [ ] Every new platform-admin route calls `require_platform_permission(...)`
- [ ] New frontend UI gating goes through `hasPermission()`, never a
      `role === "owner"`-style check
- [ ] New user-facing strings were added in **both** English and Spanish
      (`frontend/lib/i18n/translations.ts`)
- [ ] No unrelated refactors bundled into this PR (open a separate PR for
      cleanup)
- [ ] If this changes environment variables, `.env.example` (and
      `docs/deployment.md` if it's required for production) is updated

## Manual verification

If this is a UI-facing change, note what you checked and where (e.g.
"tested at desktop and 375px mobile width in Chrome"). If it's a
backend-only change, note anything you verified beyond the automated
tests.

## Related issues

Closes #
