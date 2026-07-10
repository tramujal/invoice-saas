import { ApiError } from "@/lib/api";

/** Recognizes the structured 403 require_verified_email raises on the
 * backend (see app/deps.py) — `detail` there is an object `{code, message}`
 * rather than the plain string every other error uses, specifically so
 * call sites can distinguish "you need to verify your email" from a
 * generic failure and show a targeted, translated message instead of the
 * backend's English text. */
export function isEmailNotVerifiedError(err: unknown): boolean {
  if (!(err instanceof ApiError) || err.status !== 403) return false;
  const body = err.body;
  if (!body || typeof body !== "object" || !("detail" in body)) return false;
  const detail = (body as { detail: unknown }).detail;
  return (
    Boolean(detail) &&
    typeof detail === "object" &&
    (detail as { code?: unknown }).code === "email_not_verified"
  );
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
