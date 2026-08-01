# GitHub Repository Polish

Recommendations for presenting this repository publicly — none of these
are files or settings this document can apply for you (repository
metadata is configured in the GitHub UI/API, not committed to the repo),
except the three templates listed at the bottom, which are already
created. Work through this once, before sharing the repo link anywhere.

## Repository description

One line, shown under the repo name everywhere it's linked (search
results, the org page, social cards). Suggested:

> Multi-tenant invoicing & quoting SaaS — FastAPI + Next.js, with a
> public API, HMAC-signed webhooks, durable background jobs, Stripe
> billing, and a platform-admin console.

Keep it under ~120 characters (GitHub truncates aggressively in some
views). Set it in **Settings → General → About**, or via `gh`:

```bash
gh repo edit OWNER/REPO --description "Multi-tenant invoicing & quoting SaaS — FastAPI + Next.js, with a public API, HMAC-signed webhooks, durable background jobs, Stripe billing, and a platform-admin console."
```

## Topics / tags

Set in the same **About** panel (or `gh repo edit --add-topic`). These
drive GitHub's own topic-based discovery — pick ones a real searcher
would actually use:

```
fastapi nextjs typescript python saas multi-tenant invoicing
billing stripe webhooks rbac postgresql sqlalchemy react
background-jobs open-source
```

Don't add more than ~15–20; a topic list that reads as keyword-stuffing
undermines the credibility this repo is otherwise built on.

## Social preview image

**Settings → General → Social preview.** This is the image shown when
the repo URL is shared on Twitter/X, LinkedIn, Slack, etc. — 1280×640px,
PNG or JPG. Recommended approach: use
`docs/screenshots/dashboard-overview.png` (see
[`docs/screenshots.md`](screenshots.md)) as a base, or compose a simple
card with the project name, the one-line description above, and 2–3 key
stat badges (985 backend tests, multi-tenant, Stripe-integrated) on a
solid background. Avoid a raw, unedited screenshot with browser chrome —
it reads as unfinished at social-card size.

## Badges

Already added to the top of [`README.md`](../README.md). Reference for
maintaining them:

| Badge | Source of truth | Update when |
| --- | --- | --- |
| CI status | `.github/workflows/ci.yml`'s own run status — GitHub generates this badge URL automatically once the repo is public: `https://github.com/OWNER/REPO/actions/workflows/ci.yml/badge.svg` | Never manually — it's live. |
| Backend tests | Static count badge (`pytest --collect-only -q`) | Whenever the backend test count meaningfully changes — don't update for every single new test, but don't let it drift by hundreds either. |
| Frontend tests | Static count badge (`cd frontend && npm test`) | Same cadence as above. |
| License | Static — MIT | Only if the license ever changes. |

Once the repo is public, replace every `OWNER/REPO` placeholder in the
README's badge block with the real GitHub path (`owner/repo-name`) — the
CI badge is broken until that's done, since GitHub can't resolve a badge
URL for a repo it doesn't recognize.

Optional additions once the repo has real GitHub activity:
`![GitHub last commit](https://img.shields.io/github/last-commit/OWNER/REPO)`,
`![GitHub release](https://img.shields.io/github/v/release/OWNER/REPO)`.
Skip stars/forks/issue-count badges until there's meaningful activity to
show — a "0" badge undersells a project more than no badge at all.

## Release naming

No releases have been cut yet. When you do:

- **Tag format:** `vMAJOR.MINOR.PATCH` (semver) — e.g. `v1.0.0` for the
  first public-ready snapshot (this phase's completion is a reasonable
  `v1.0.0` candidate).
- **Pre-1.0 vs post-1.0:** this project is feature-complete enough to
  justify starting at `v1.0.0` rather than lingering in `v0.x` — the
  audits this phase followed (architecture, production-readiness,
  security, UX) are exactly the bar "1.0" implies.
- **Branch:** tag from `main` only, after CI is green.

```bash
git tag -a v1.0.0 -m "v1.0.0 — first public release"
git push origin v1.0.0
```

## GitHub Releases notes

Use `gh release create` (or the GitHub UI) pointed at the tag above.
Suggested structure for the `v1.0.0` notes, drawing directly from what's
already true of this codebase (see [`docs/portfolio.md`](portfolio.md)
for the full narrative to draw from for future release notes too):

```markdown
## v1.0.0 — First public release

A production-grade, multi-tenant invoicing & quoting SaaS: tenant
isolation enforced structurally, RBAC enforced identically across REST,
the public API, and the AI agent, a durable background-job queue,
HMAC-signed outbound webhooks, and commercial plans wired to real Stripe
billing.

### Highlights
- Multi-tenant invoicing & quoting, full lifecycle (draft → sent →
  accepted/rejected → converted)
- Public REST API + scoped API keys
- Outbound webhooks, HMAC-signed, durably delivered by a background
  worker with automatic retries
- Stripe billing integration behind a provider-agnostic interface
- AI business assistant (Claude/Gemini) — propose-then-confirm, never
  auto-executing
- Platform-administration console, fully separate RBAC from tenant roles
- 985 backend tests, 285 frontend tests, CI merge-blocking on every PR

### Documentation
- [Architecture](../docs/architecture.md)
- [Deployment guide](../docs/deployment.md)
- [Portfolio / engineering writeup](../docs/portfolio.md)

**Full Changelog**: this is the first tagged release.
```

For subsequent releases, keep the same shape (Highlights / Fixes /
Documentation) and let `git log vPREV..vNEW --oneline` seed the list of
what to actually mention — don't hand-write a changelog from memory.

## Issue templates

Created — see [`.github/ISSUE_TEMPLATE/bug_report.md`](../.github/ISSUE_TEMPLATE/bug_report.md)
and [`.github/ISSUE_TEMPLATE/feature_request.md`](../.github/ISSUE_TEMPLATE/feature_request.md).
GitHub picks these up automatically (no config needed) and offers them
as choices the moment someone clicks "New issue." Nothing further to do
unless you later want a `config.yml` alongside them to add external
links (e.g. a Discord/discussions link) to that chooser screen.

## Pull request template

Created — see [`.github/PULL_REQUEST_TEMPLATE.md`](../.github/PULL_REQUEST_TEMPLATE.md).
GitHub auto-populates this into the PR description box for every new
PR against this repo. Nothing further to configure.
