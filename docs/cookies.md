# Cookie & Tracking Audit (Phase 25)

## Method

Grepped the entire codebase (backend and frontend) for `set_cookie`,
`Response.*cookie`, `request.cookies`, `document.cookie`, `js-cookie`,
and every common third-party analytics/marketing/tracking script
signature (Google Analytics/`gtag`, Google Tag Manager, Mixpanel,
Segment, Facebook Pixel, Hotjar, PostHog, Amplitude, Sentry, Plausible).

## Result

**Before this phase: zero cookies, zero third-party scripts, anywhere in
this application.** Authentication is a Bearer JWT stored in
`localStorage` (see `docs/google_auth.md`'s own session-storage audit) —
not a single cookie was set by the backend or read by the frontend.
There is no analytics SDK, no tag manager, no marketing pixel, no error-
tracking beacon, nothing loaded from a third-party domain at all.

**After this phase: exactly one cookie**, added by Google Sign-In (Part
1 of this phase):

| Cookie | Set by | Purpose | Lifetime | Flags |
| --- | --- | --- | --- | --- |
| `google_oauth_state` | `GET /auth/google/start` | CSRF-binds the OAuth redirect to the browser that started it (double-submit against the server-stored `state`/`nonce` row) — see `docs/google_auth.md`'s own Security section for exactly what this prevents. | 10 minutes; explicitly deleted at the end of `/auth/google/callback` (both the success and every failure path) | `HttpOnly`, `Secure` (production only), `SameSite=Lax`, `Path=/auth/google` |

That is the complete inventory. No other cookie is ever set, and no
third-party script was added by this phase either — `GoogleSignInButton`
navigates the whole page to this app's own backend
(`{apiBaseUrl}/auth/google/start`), which itself redirects to Google;
the frontend never embeds a Google script, iframe, or SDK.

## Consent decision

**No cookie banner, preferences dialog, or consent-storage system was
built.**

This is a deliberate reading of this phase's own instructions, not an
oversight: *"If only strictly necessary cookies exist: DO NOT show a
fake consent banner."* The one cookie this phase introduces is:

- **Strictly necessary** — it exists to prevent a real security attack
  (OAuth login-CSRF), not to track, profile, personalize, or measure
  anything about the visitor. Under every major cookie-consent framework
  (GDPR/ePrivacy's "strictly necessary" exemption, CCPA, etc.), a cookie
  whose sole purpose is security/technical operation of a feature the
  user actively invoked does not require consent.
- **Short-lived and narrowly scoped** — 10 minutes, path-scoped to
  `/auth/google`, carrying no identity or profiling data (an opaque
  random value only).
- **Never set unless the user clicks "Continue with Google"** — an
  anonymous visitor who never touches that button never receives this
  cookie at all; it is not set on page load.

Building a consent banner for this would be exactly the "fake consent
banner" this phase's own instructions explicitly forbid — a compliance-
theater UI gating a cookie that legitimately needs no gate. If a future
phase adds a genuinely optional cookie (analytics, marketing,
personalization, A/B testing, or any third-party script), **that** phase
must build the real thing: banner, preferences dialog, consent storage
with a version and timestamp, a revoke path, and EN/ES translations, with
no such script loading before consent is given. None of that exists
today because none of the underlying cookies it would gate exist today.

## This is not a legal compliance claim

This document describes what the application technically does — it is
not a legal opinion, and it does not claim compliance with GDPR, CCPA, or
any other privacy regulation. An operator deploying this application
should have their own privacy policy and consult counsel as appropriate
for their jurisdiction and user base, independent of this technical
audit.
