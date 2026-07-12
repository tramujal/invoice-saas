"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import Link from "next/link";

import { useToast } from "@/components/ui/toast";
import { ApiError, apiFetch, orgPath } from "@/lib/api";
import {
  getUserEmail,
  setEmailVerified as cacheEmailVerified,
  updateOrganizationCurrency,
  updateOrganizationLanguage,
  updateOrganizationName,
} from "@/lib/auth-storage";
import { formatApiError, isEmailNotVerifiedError } from "@/lib/format-api-error";
import { useTranslation } from "@/lib/i18n/useTranslation";
import {
  CURRENCY_CODES,
  REMINDER_DAY_LIST_MAX_LENGTH,
  REMINDER_DAY_MAX,
  REMINDER_DAY_MIN,
  TAX_LABEL_OPTIONS,
  getCurrencyLabel,
  getTimezoneOptions,
  LANGUAGES,
  LANGUAGE_LABELS,
  type CurrencyCode,
  type Language,
  type TaxLabelOption,
} from "@/lib/organization-settings";
import type { MeResponse, OrganizationProfile } from "@/lib/types";

/** Parses a comma-separated day-list input (e.g. "7, 3, 1") into a
 * validated number[], or null if it's malformed/out of bounds -- mirrors
 * the backend's own bounds (app.reminder_settings) so the user gets
 * immediate feedback rather than a round-trip 422. Blank input is valid
 * and means "no reminders at this offset" (an empty list). */
function parseDayListInput(raw: string): number[] | null {
  const trimmed = raw.trim();
  if (!trimmed) return [];
  const parts = trimmed.split(",").map((p) => p.trim());
  const days: number[] = [];
  for (const part of parts) {
    if (!/^\d+$/.test(part)) return null;
    const value = Number(part);
    if (value < REMINDER_DAY_MIN || value > REMINDER_DAY_MAX) return null;
    days.push(value);
  }
  if (days.length > REMINDER_DAY_LIST_MAX_LENGTH) return null;
  return days;
}

function formatDayList(days: number[]): string {
  return days.join(", ");
}

const LIMITS = {
  name: 255,
  business_name: 255,
  tax_id: 64,
  address: 512,
  phone: 64,
  email: 255,
  logo_url: 1024,
} as const;

type FormState = {
  name: string;
  business_name: string;
  tax_id: string;
  address: string;
  phone: string;
  email: string;
  logo_url: string;
  language: Language;
  currency_code: CurrencyCode;
  tax_label: TaxLabelOption;
  timezone: string;
  reminders_enabled: boolean;
  reminder_before_due_days: string;
  reminder_on_due_date: boolean;
  reminder_after_due_days: string;
};

const EMPTY_FORM: FormState = {
  name: "",
  business_name: "",
  tax_id: "",
  address: "",
  phone: "",
  email: "",
  logo_url: "",
  language: "en",
  currency_code: "USD",
  tax_label: "Tax ID",
  timezone: "UTC",
  reminders_enabled: false,
  reminder_before_due_days: "3",
  reminder_on_due_date: true,
  reminder_after_due_days: "7",
};

function toFormState(profile: OrganizationProfile): FormState {
  return {
    name: profile.name,
    business_name: profile.business_name ?? "",
    tax_id: profile.tax_id ?? "",
    address: profile.address ?? "",
    phone: profile.phone ?? "",
    email: profile.email ?? "",
    logo_url: profile.logo_url ?? "",
    language: (LANGUAGES as readonly string[]).includes(profile.language)
      ? (profile.language as Language)
      : "en",
    currency_code: (CURRENCY_CODES as readonly string[]).includes(profile.currency_code)
      ? (profile.currency_code as CurrencyCode)
      : "USD",
    tax_label: (TAX_LABEL_OPTIONS as readonly string[]).includes(profile.tax_label)
      ? (profile.tax_label as TaxLabelOption)
      : "Tax ID",
    timezone: profile.timezone,
    reminders_enabled: profile.reminders_enabled,
    reminder_before_due_days: formatDayList(profile.reminder_before_due_days),
    reminder_on_due_date: profile.reminder_on_due_date,
    reminder_after_due_days: formatDayList(profile.reminder_after_due_days),
  };
}

// Translated at render time, not inside the useCallback below, since
// useTranslation()'s t is not identity-stable (see dashboard/customers
// pages for the same pattern).
const GENERIC_LOAD_ERROR = "__generic_load_error__";

export default function SettingsPage() {
  const toast = useToast();
  const { t } = useTranslation();
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [nameError, setNameError] = useState<string | null>(null);
  const [reminderDaysError, setReminderDaysError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  // Hydration-safe: read only after mount, like organizationName elsewhere.
  const [userEmail, setUserEmail] = useState<string | null>(null);
  useEffect(() => {
    setUserEmail(getUserEmail());
  }, []);

  // Fetched directly from /auth/me (rather than read from the cached
  // localStorage flag AppShell also maintains) so this section always
  // shows the true current status rather than a value that might not have
  // been refreshed yet on this render.
  const [emailVerified, setEmailVerified] = useState<boolean | null>(null);
  useEffect(() => {
    apiFetch<MeResponse>("/auth/me")
      .then((me) => {
        setEmailVerified(me.user.email_verified);
        cacheEmailVerified(me.user.email_verified);
      })
      .catch(() => {
        // Non-critical: the rest of the page still loads via its own
        // load() below. Leaving emailVerified as null just hides this one
        // status line rather than surfacing an error banner for it.
      });
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const profile = await apiFetch<OrganizationProfile>(orgPath());
      setForm(toFormState(profile));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : GENERIC_LOAD_ERROR);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  function update<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();

    const name = form.name.trim();
    if (!name) {
      setNameError(t("common.errorRequired", { field: t("auth.organizationNameLabel") }));
      return;
    }
    setNameError(null);

    const beforeDueDays = parseDayListInput(form.reminder_before_due_days);
    const afterDueDays = parseDayListInput(form.reminder_after_due_days);
    if (beforeDueDays === null || afterDueDays === null) {
      setReminderDaysError(t("settings.invalidReminderDays"));
      return;
    }
    setReminderDaysError(null);

    const loadingId = toast.loading(t("settings.toastSaving"));
    setIsSubmitting(true);
    try {
      const updated = await apiFetch<OrganizationProfile>(orgPath(), {
        method: "PATCH",
        body: JSON.stringify({
          name,
          business_name: form.business_name.trim(),
          tax_id: form.tax_id.trim(),
          address: form.address.trim(),
          phone: form.phone.trim(),
          email: form.email.trim(),
          logo_url: form.logo_url.trim(),
          language: form.language,
          currency_code: form.currency_code,
          tax_label: form.tax_label,
          timezone: form.timezone,
          reminders_enabled: form.reminders_enabled,
          reminder_before_due_days: beforeDueDays,
          reminder_on_due_date: form.reminder_on_due_date,
          reminder_after_due_days: afterDueDays,
        }),
      });
      setForm(toFormState(updated));
      updateOrganizationName(updated.name);
      updateOrganizationCurrency(updated.currency_code);
      updateOrganizationLanguage(updated.language);
      toast.dismiss(loadingId);
      toast.success(t("settings.toastSaved"));
    } catch (err) {
      toast.dismiss(loadingId);
      toast.error(
        isEmailNotVerifiedError(err)
          ? t("errors.emailNotVerified")
          : formatApiError(err, t("settings.toastSaveError"))
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  const disabled = isSubmitting || loading;

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
          {t("settings.title")}
        </h1>
        <p className="mt-1 text-sm text-slate-500">{t("settings.subtitle")}</p>
      </header>

      {error ? (
        <div
          className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800"
          role="alert"
        >
          {error === GENERIC_LOAD_ERROR ? t("settings.loadError") : error}
        </div>
      ) : null}

      <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-6">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
          {t("settings.accountSectionTitle")}
        </h2>
        <div className="mt-4">
          <p className="text-sm font-medium text-slate-700">{t("common.email")}</p>
          <p className="mt-1 text-sm text-slate-900">{userEmail ?? "—"}</p>
          <p className="mt-1 text-xs text-slate-500">{t("settings.accountEmailHelp")}</p>
          {emailVerified !== null ? (
            <span
              className={`mt-2 inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${
                emailVerified
                  ? "bg-emerald-100 text-emerald-800"
                  : "bg-amber-100 text-amber-800"
              }`}
            >
              <span
                className={`h-1.5 w-1.5 rounded-full ${
                  emailVerified ? "bg-emerald-600" : "bg-amber-600"
                }`}
                aria-hidden
              />
              {emailVerified
                ? t("settings.emailVerifiedLabel")
                : t("settings.emailNotVerifiedLabel")}
            </span>
          ) : null}
        </div>
        <div className="mt-5">
          <Link
            href="/forgot-password"
            className="inline-flex items-center justify-center rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium text-slate-800 shadow-sm hover:bg-slate-50"
          >
            {t("settings.changePasswordAction")}
          </Link>
          <p className="mt-1.5 text-xs text-slate-500">{t("settings.changePasswordHelp")}</p>
        </div>
      </section>

      <form onSubmit={(e) => void onSubmit(e)} className="space-y-6" aria-busy={loading}>
        <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-6">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
            {t("settings.organizationSectionTitle")}
          </h2>
          <div className="mt-4">
            <label htmlFor="org-name" className="text-sm font-medium text-slate-700">
              {t("auth.organizationNameLabel")} <span className="text-red-600">*</span>
            </label>
            <input
              id="org-name"
              type="text"
              value={form.name}
              onChange={(e) => update("name", e.target.value)}
              disabled={disabled}
              maxLength={LIMITS.name}
              className="mt-1 w-full max-w-md rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none ring-slate-400 focus:ring-2 disabled:bg-slate-50"
              aria-invalid={Boolean(nameError)}
              aria-describedby={nameError ? "org-name-err" : undefined}
            />
            {nameError ? (
              <p id="org-name-err" className="mt-1 text-xs text-red-600" role="alert">
                {nameError}
              </p>
            ) : null}
            <p className="mt-1 text-xs text-slate-500">{t("settings.orgNameHelp")}</p>
          </div>
        </section>

        <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-6">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
            {t("settings.businessDetailsSectionTitle")}
          </h2>
          <p className="mt-1 text-sm text-slate-500">
            {t("settings.businessDetailsSubtitle")}
          </p>

          <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label
                htmlFor="business-name"
                className="text-sm font-medium text-slate-700"
              >
                {t("settings.businessNameLabel")}
              </label>
              <input
                id="business-name"
                type="text"
                value={form.business_name}
                onChange={(e) => update("business_name", e.target.value)}
                disabled={disabled}
                maxLength={LIMITS.business_name}
                placeholder={t("settings.businessNamePlaceholder")}
                className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none ring-slate-400 focus:ring-2 disabled:bg-slate-50"
              />
            </div>

            <div>
              <label htmlFor="tax-id" className="text-sm font-medium text-slate-700">
                {t("settings.taxIdLabel")}
              </label>
              <input
                id="tax-id"
                type="text"
                value={form.tax_id}
                onChange={(e) => update("tax_id", e.target.value)}
                disabled={disabled}
                maxLength={LIMITS.tax_id}
                className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none ring-slate-400 focus:ring-2 disabled:bg-slate-50"
              />
            </div>

            <div>
              <label htmlFor="org-phone" className="text-sm font-medium text-slate-700">
                {t("common.phone")}
              </label>
              <input
                id="org-phone"
                type="tel"
                value={form.phone}
                onChange={(e) => update("phone", e.target.value)}
                disabled={disabled}
                maxLength={LIMITS.phone}
                className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none ring-slate-400 focus:ring-2 disabled:bg-slate-50"
              />
            </div>

            <div>
              <label htmlFor="org-email" className="text-sm font-medium text-slate-700">
                {t("common.email")}
              </label>
              <input
                id="org-email"
                type="email"
                value={form.email}
                onChange={(e) => update("email", e.target.value)}
                disabled={disabled}
                maxLength={LIMITS.email}
                className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none ring-slate-400 focus:ring-2 disabled:bg-slate-50"
              />
            </div>

            <div className="sm:col-span-2">
              <label htmlFor="org-address" className="text-sm font-medium text-slate-700">
                {t("common.address")}
              </label>
              <textarea
                id="org-address"
                value={form.address}
                onChange={(e) => update("address", e.target.value)}
                disabled={disabled}
                maxLength={LIMITS.address}
                rows={3}
                className="mt-1 w-full resize-y rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none ring-slate-400 focus:ring-2 disabled:bg-slate-50"
              />
            </div>

            <div className="sm:col-span-2">
              <label htmlFor="logo-url" className="text-sm font-medium text-slate-700">
                {t("settings.logoUrlLabel")}
              </label>
              <input
                id="logo-url"
                type="url"
                value={form.logo_url}
                onChange={(e) => update("logo_url", e.target.value)}
                disabled={disabled}
                maxLength={LIMITS.logo_url}
                placeholder="https://…"
                className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none ring-slate-400 focus:ring-2 disabled:bg-slate-50"
              />
              <p className="mt-1 text-xs text-slate-500">{t("settings.logoUrlHelp")}</p>
            </div>
          </div>
        </section>

        <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-6">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
            {t("settings.localizationSectionTitle")}
          </h2>
          <p className="mt-1 text-sm text-slate-500">
            {t("settings.localizationSubtitle")}
          </p>

          <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <div>
              <label htmlFor="org-language" className="text-sm font-medium text-slate-700">
                {t("settings.languageFieldLabel")}
              </label>
              <select
                id="org-language"
                value={form.language}
                onChange={(e) => update("language", e.target.value as Language)}
                disabled={disabled}
                className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none ring-slate-400 focus:ring-2 disabled:bg-slate-50"
              >
                {LANGUAGES.map((code) => (
                  <option key={code} value={code}>
                    {LANGUAGE_LABELS[code]}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label htmlFor="org-currency" className="text-sm font-medium text-slate-700">
                {t("settings.currencyFieldLabel")}
              </label>
              <select
                id="org-currency"
                value={form.currency_code}
                onChange={(e) => update("currency_code", e.target.value as CurrencyCode)}
                disabled={disabled}
                className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none ring-slate-400 focus:ring-2 disabled:bg-slate-50"
              >
                {CURRENCY_CODES.map((code) => (
                  <option key={code} value={code}>
                    {getCurrencyLabel(t, code)}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label htmlFor="org-tax-label" className="text-sm font-medium text-slate-700">
                {t("settings.taxLabelFieldLabel")}
              </label>
              <select
                id="org-tax-label"
                value={form.tax_label}
                onChange={(e) => update("tax_label", e.target.value as TaxLabelOption)}
                disabled={disabled}
                className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none ring-slate-400 focus:ring-2 disabled:bg-slate-50"
              >
                {TAX_LABEL_OPTIONS.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
              <p className="mt-1 text-xs text-slate-500">{t("settings.taxLabelHelp")}</p>
            </div>

            <div>
              <label htmlFor="org-timezone" className="text-sm font-medium text-slate-700">
                {t("settings.timezoneFieldLabel")}
              </label>
              <select
                id="org-timezone"
                value={form.timezone}
                onChange={(e) => update("timezone", e.target.value)}
                disabled={disabled}
                className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none ring-slate-400 focus:ring-2 disabled:bg-slate-50"
              >
                {getTimezoneOptions(form.timezone).map((tz) => (
                  <option key={tz} value={tz}>
                    {tz}
                  </option>
                ))}
              </select>
              <p className="mt-1 text-xs text-slate-500">{t("settings.timezoneHelp")}</p>
            </div>
          </div>
        </section>

        <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-6">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
            {t("settings.reminderSectionTitle")}
          </h2>
          <p className="mt-1 text-sm text-slate-500">
            {t("settings.reminderSectionSubtitle")}
          </p>

          <div className="mt-4">
            <label className="flex items-center gap-2 text-sm font-medium text-slate-700">
              <input
                type="checkbox"
                checked={form.reminders_enabled}
                onChange={(e) => update("reminders_enabled", e.target.checked)}
                disabled={disabled}
                className="h-4 w-4 rounded border-slate-300 text-slate-900 focus:ring-slate-400"
              />
              {t("settings.remindersEnabledLabel")}
            </label>
          </div>

          <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label
                htmlFor="reminder-before-days"
                className="text-sm font-medium text-slate-700"
              >
                {t("settings.reminderBeforeDueLabel")}
              </label>
              <input
                id="reminder-before-days"
                type="text"
                value={form.reminder_before_due_days}
                onChange={(e) => update("reminder_before_due_days", e.target.value)}
                disabled={disabled || !form.reminders_enabled}
                placeholder={t("settings.reminderDaysPlaceholder")}
                className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none ring-slate-400 focus:ring-2 disabled:bg-slate-50"
              />
            </div>

            <div>
              <label
                htmlFor="reminder-after-days"
                className="text-sm font-medium text-slate-700"
              >
                {t("settings.reminderAfterDueLabel")}
              </label>
              <input
                id="reminder-after-days"
                type="text"
                value={form.reminder_after_due_days}
                onChange={(e) => update("reminder_after_due_days", e.target.value)}
                disabled={disabled || !form.reminders_enabled}
                placeholder={t("settings.reminderDaysPlaceholder")}
                className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none ring-slate-400 focus:ring-2 disabled:bg-slate-50"
              />
            </div>

            <div className="sm:col-span-2">
              <label className="flex items-center gap-2 text-sm font-medium text-slate-700">
                <input
                  type="checkbox"
                  checked={form.reminder_on_due_date}
                  onChange={(e) => update("reminder_on_due_date", e.target.checked)}
                  disabled={disabled || !form.reminders_enabled}
                  className="h-4 w-4 rounded border-slate-300 text-slate-900 focus:ring-slate-400"
                />
                {t("settings.reminderOnDueDateLabel")}
              </label>
            </div>
          </div>
          {reminderDaysError ? (
            <p className="mt-2 text-xs text-red-600" role="alert">
              {reminderDaysError}
            </p>
          ) : (
            <p className="mt-2 text-xs text-slate-500">{t("settings.reminderDaysHelp")}</p>
          )}
        </section>

        <div className="flex justify-end">
          <button
            type="submit"
            disabled={disabled}
            className="inline-flex items-center justify-center gap-2 rounded-lg bg-slate-900 px-5 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-70"
          >
            {isSubmitting ? t("common.saving") : t("common.saveChanges")}
          </button>
        </div>
      </form>
    </div>
  );
}
