import { ApiError } from "@/lib/api";
import type { TranslateFn } from "@/lib/i18n/useTranslation";

/** Every stable, language-neutral error code the backend can send for an
 * AI assistant action (see app/routers/assistant.py and
 * app/routers/assistant_actions.py) — translated here, in one place, so
 * both the streamed error events on the chat page and the confirm/cancel
 * HTTP error responses map to the same localized text. Falls back to a
 * generic message for anything not in this list (including transport-
 * level codes like ai_timeout/ai_provider_error, which reuse the
 * existing assistant.errorTimeout/errorGeneric keys via the page itself). */
const KNOWN_CODES = new Set([
  "assistant_action_not_found",
  "assistant_action_expired",
  "assistant_action_already_used",
  "assistant_action_not_authorized",
  "assistant_action_invalid",
  "assistant_action_confirmation_required",
  "assistant_action_execution_failed",
  "ambiguous_customer",
  "customer_not_found",
  "invoice_not_found",
  "customer_email_missing",
  "rate_limit_exceeded",
]);

export function assistantErrorMessageForCode(t: TranslateFn, code: string): string {
  if (KNOWN_CODES.has(code)) {
    return t(`assistant.error.${code}`);
  }
  return t("assistant.error.generic");
}

/** Extracts the backend's `detail.code` from a confirm/cancel ApiError
 * (same {code, message} shape as every other structured error in this
 * app — see app/deps.py's require_verified_email for the precedent) and
 * translates it; falls back to a generic message for anything else
 * (network failure, unexpected shape, etc). */
export function assistantErrorMessageForApiError(t: TranslateFn, err: unknown): string {
  if (err instanceof ApiError) {
    const body = err.body;
    if (body && typeof body === "object" && "detail" in body) {
      const detail = (body as { detail: unknown }).detail;
      if (detail && typeof detail === "object" && "code" in detail) {
        return assistantErrorMessageForCode(t, String((detail as { code: unknown }).code));
      }
    }
  }
  return t("assistant.error.generic");
}
