import { ApiError } from "@/lib/api";
import type { PlanLimitReachedDetail } from "@/lib/types";

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
