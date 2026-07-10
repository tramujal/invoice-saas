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
