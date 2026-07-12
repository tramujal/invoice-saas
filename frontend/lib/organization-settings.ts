export const LANGUAGES = ["en", "es"] as const;
export type Language = (typeof LANGUAGES)[number];

export const LANGUAGE_LABELS: Record<Language, string> = {
  en: "English",
  es: "Español",
};

import type { TranslateFn } from "@/lib/i18n/useTranslation";
import type { Customer } from "@/lib/types";

/** The single shared list of currencies this app supports, everywhere a
 * currency needs to be picked or displayed (organization default in
 * Settings, per-invoice currency on the invoice form, dashboard currency
 * selector). Adding a new currency means adding one entry here (plus its
 * settings.currencyXXX translation keys) — no call site changes. */
export const CURRENCY_CODES = ["USD", "UYU", "EUR"] as const;
export type CurrencyCode = (typeof CURRENCY_CODES)[number];

function isCurrencyCode(value: string | null | undefined): value is CurrencyCode {
  return (CURRENCY_CODES as readonly string[]).includes(value ?? "");
}

/** Single source of truth for what currency a *new* invoice's selector
 * should be preselected with, given the currently chosen customer (if
 * any) and the organization's default currency.
 *
 * Currently this always returns the organization's default — Customer has
 * no preferred-currency field yet. It takes `customer` as a parameter (not
 * just `orgCurrency`) so that a future customer-level preferred currency
 * only requires changing the body of this function — e.g. preferring
 * `customer.preferred_currency_code` when set — with no changes needed at
 * its call site on the invoice form, which already recomputes this
 * whenever the selected customer changes and only applies the result
 * while the user hasn't manually picked a currency themselves. */
export function resolveDefaultInvoiceCurrency(
  customer: Customer | null,
  orgCurrency: string | null
): CurrencyCode {
  return isCurrencyCode(orgCurrency) ? orgCurrency : "USD";
}

function currencyLabelKey(code: CurrencyCode): string {
  return `settings.currency${code}`;
}

/** Human-readable label for a currency code, e.g. "USD — US Dollar" (or
 * "USD — Dólar estadounidense" in Spanish). Shared by every currency
 * picker in the app so they never drift out of sync with each other. */
export function getCurrencyLabel(t: TranslateFn, code: CurrencyCode): string {
  return t(currencyLabelKey(code));
}

export const TAX_LABEL_OPTIONS = ["Tax ID", "RUT", "CUIT", "NIF"] as const;
export type TaxLabelOption = (typeof TAX_LABEL_OPTIONS)[number];

/** A curated subset of IANA timezone identifiers -- not an exhaustive
 * mirror of the backend's validation set (it accepts any identifier
 * zoneinfo knows), just a reasonable picklist covering major regions.
 * getTimezoneOptions() below always includes the organization's current
 * value even if it falls outside this curated list, so an org configured
 * via a value not in this list (e.g. hand-edited data) never loses its
 * own setting from the dropdown. */
export const TIMEZONE_OPTIONS = [
  "UTC",
  "America/New_York",
  "America/Chicago",
  "America/Denver",
  "America/Los_Angeles",
  "America/Mexico_City",
  "America/Bogota",
  "America/Lima",
  "America/Santiago",
  "America/Sao_Paulo",
  "America/Argentina/Buenos_Aires",
  "America/Montevideo",
  "Europe/London",
  "Europe/Madrid",
  "Europe/Paris",
  "Europe/Berlin",
  "Europe/Rome",
  "Africa/Cairo",
  "Africa/Johannesburg",
  "Asia/Dubai",
  "Asia/Kolkata",
  "Asia/Shanghai",
  "Asia/Tokyo",
  "Asia/Singapore",
  "Australia/Sydney",
  "Pacific/Auckland",
] as const;

/** Always includes `currentValue` even when it isn't in the curated list
 * above, so an organization's existing timezone is never silently dropped
 * from its own settings dropdown. */
export function getTimezoneOptions(currentValue: string): string[] {
  if (!currentValue || (TIMEZONE_OPTIONS as readonly string[]).includes(currentValue)) {
    return [...TIMEZONE_OPTIONS];
  }
  return [currentValue, ...TIMEZONE_OPTIONS];
}

/** Preset day-offset choices for the reminder settings form, mirroring
 * the backend's bounds (app.reminder_settings: 1-90 days, max 5 entries)
 * without hardcoding validation here — the backend is the source of
 * truth for what's actually accepted. */
export const REMINDER_BEFORE_DUE_PRESETS = [1, 3, 7, 14, 30] as const;
export const REMINDER_AFTER_DUE_PRESETS = [1, 3, 7, 14, 30] as const;
export const REMINDER_DAY_MIN = 1;
export const REMINDER_DAY_MAX = 90;
export const REMINDER_DAY_LIST_MAX_LENGTH = 5;
