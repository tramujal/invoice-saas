import { ApiError } from "@/lib/api";
import type { CapabilityDeniedDetail, PlanLimitReachedDetail, TaxIdDuplicateDetail } from "@/lib/types";

/** Shared shape check behind isEmailNotVerifiedError/isRateLimitedError:
 * both recognize a structured `detail: {code, message}` object (rather
 * than the plain string every other error uses) at a given status, so
 * call sites can distinguish a specific, expected failure from a generic
 * one and show a targeted, translated message instead of the backend's
 * English text. One place to check the shape keeps the two predicates
 * from drifting apart. */
function hasDetailCode(err: unknown, status: number, code: string): boolean {
  if (!(err instanceof ApiError) || err.status !== status) return false;
  const body = err.body;
  if (!body || typeof body !== "object" || !("detail" in body)) return false;
  const detail = (body as { detail: unknown }).detail;
  return (
    Boolean(detail) &&
    typeof detail === "object" &&
    (detail as { code?: unknown }).code === code
  );
}

/** Recognizes the structured 403 require_verified_email raises on the
 * backend (see app/deps.py). */
export function isEmailNotVerifiedError(err: unknown): boolean {
  return hasDetailCode(err, 403, "email_not_verified");
}

/** Recognizes the structured 429 enforce_rate_limit raises on the backend
 * (see app/rate_limit.py) — the same `detail.code` convention as above,
 * just at 429 with code "rate_limit_exceeded". */
export function isRateLimitedError(err: unknown): boolean {
  return hasDetailCode(err, 429, "rate_limit_exceeded");
}

/** Extracts the backend's stable `detail.code` from a structured error
 * response, or null if this error doesn't use that shape -- shared by any
 * call site that needs to branch on a specific machine-readable code
 * (e.g. the reminder endpoint's reminders_disabled/invoice_already_paid/
 * reminder_already_sent codes) rather than just showing raw text. */
export function getApiErrorCode(err: unknown): string | null {
  if (!(err instanceof ApiError)) return null;
  const body = err.body;
  if (!body || typeof body !== "object" || !("detail" in body)) return null;
  const detail = (body as { detail: unknown }).detail;
  if (!detail || typeof detail !== "object") return null;
  const code = (detail as { code?: unknown }).code;
  return typeof code === "string" ? code : null;
}

/** Recognizes the structured 409 plan_limit_reached (see
 * app.services.plan_limits.PlanLimitExceededError) and returns its full
 * detail payload -- not just the code, since every caller needs
 * resource/used/limit/plan to render the dialog, never the human
 * `message` string. Returns null for any other error shape. */
export function getPlanLimitReachedDetail(err: unknown): PlanLimitReachedDetail | null {
  if (!hasDetailCode(err, 409, "plan_limit_reached")) return null;
  const body = (err as ApiError).body as { detail: PlanLimitReachedDetail };
  return body.detail;
}

/** Recognizes the structured 403 feature_not_available (see
 * app.billing.enforcement.CapabilityDeniedError) and returns its full
 * detail payload -- Phase 17B's all-or-nothing plan-feature gates (AI,
 * Analytics), distinct from plan_limit_reached's used-vs-limit quota
 * shape above. Returns null for any other error shape. */
export function getCapabilityDeniedDetail(err: unknown): CapabilityDeniedDetail | null {
  if (!hasDetailCode(err, 403, "feature_not_available")) return null;
  const body = (err as ApiError).body as { detail: CapabilityDeniedDetail };
  return body.detail;
}

/** Recognizes the structured 409 duplicate_tax_id (see
 * app.services.customers.TaxIdDuplicateError) and returns its full detail
 * payload -- Phase UX5's server-side, defense-in-depth tax-id block.
 * Returns null for any other error shape. */
export function getTaxIdDuplicateDetail(err: unknown): TaxIdDuplicateDetail | null {
  if (!hasDetailCode(err, 409, "duplicate_tax_id")) return null;
  const body = (err as ApiError).body as { detail: TaxIdDuplicateDetail };
  return body.detail;
}


/** Phase 28 -- an invalid Uruguayan RUT. 422 (a malformed field), NOT
 * 409: it is deliberately distinct from duplicate_tax_id so the UI never
 * tells the user "duplicate" about a value that isn't even a valid RUT.
 * The caller renders a translated message; the code is the contract. */
export function isInvalidUruguayRutError(err: unknown): boolean {
  return hasDetailCode(err, 422, "invalid_uruguay_rut");
}

export function formatApiError(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    const body = err.body;
    if (body && typeof body === "object" && "detail" in body) {
      const detail = (body as { detail: unknown }).detail;
      if (typeof detail === "string") return detail;
      if (Array.isArray(detail)) {
        return detail
          .map((item) =>
            typeof item === "object" && item && "msg" in item
              ? String((item as { msg: unknown }).msg)
              : JSON.stringify(item)
          )
          .join(" ");
      }
    }
    return err.message;
  }
  return fallback;
}
