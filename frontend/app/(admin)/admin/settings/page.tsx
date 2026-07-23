"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { SettingsChangeDialog, type SettingsFieldChange } from "@/components/admin/SettingsChangeDialog";
import { VersionConflictDialog } from "@/components/admin/VersionConflictDialog";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Select } from "@/components/ui/Input";
import { PageHeader } from "@/components/ui/PageHeader";
import { useToast } from "@/components/ui/toast";
import { ApiError, apiFetch } from "@/lib/api";
import { formatApiError, getApiErrorCode } from "@/lib/format-api-error";
import { useTranslation } from "@/lib/i18n/useTranslation";
import { CURRENCY_CODES, LANGUAGES, LANGUAGE_LABELS, getCurrencyLabel, type CurrencyCode, type Language } from "@/lib/organization-settings";
import type { PlatformSettings, PlatformSettingsUpdateRequest } from "@/lib/types";

const GENERIC_LOAD_ERROR = "__generic_load_error__";
const MAX_ORIGINS_SHOWN = 3;

type EditableField = keyof Omit<PlatformSettingsUpdateRequest, "reason" | "expected_version">;

/** Local edited copy of just the editable fields -- kept separate from
 * `data` (the persisted, backend-confirmed state) so toggling a switch
 * never "looks saved" until the PATCH response actually comes back. See
 * this page's own save flow: draft only ever becomes the displayed
 * truth once it's also `data`. */
type Draft = Pick<PlatformSettings, EditableField>;

function draftFromData(data: PlatformSettings): Draft {
  return {
    maintenance_mode: data.maintenance_mode,
    registrations_enabled: data.registrations_enabled,
    ai_enabled: data.ai_enabled,
    emails_enabled: data.emails_enabled,
    invoice_reminders_enabled: data.invoice_reminders_enabled,
    quote_reminders_enabled: data.quote_reminders_enabled,
    default_language: data.default_language,
    default_currency: data.default_currency,
  };
}

/** Per-(field, new-value) warning copy -- only the specific transitions
 * the spec calls "major platform capability" changes get a warning;
 * turning a switch back on, or changing a default, is routine. */
function warningKeyFor(field: EditableField, newValue: boolean | string): string | null {
  if (field === "maintenance_mode" && newValue === true) return "admin.warningMaintenanceMode";
  if (field === "registrations_enabled" && newValue === false) return "admin.warningRegistrationsDisabled";
  if (field === "ai_enabled" && newValue === false) return "admin.warningAiDisabled";
  if (field === "emails_enabled" && newValue === false) return "admin.warningEmailsDisabled";
  if (field === "invoice_reminders_enabled" && newValue === false) return "admin.warningInvoiceRemindersDisabled";
  if (field === "quote_reminders_enabled" && newValue === false) return "admin.warningQuoteRemindersDisabled";
  return null;
}

type ToggleRowProps = {
  id: string;
  label: string;
  description: string;
  checked: boolean;
  disabled: boolean;
  onChange: (next: boolean) => void;
};

/** The one boolean-switch control every editable setting on this page
 * uses -- a plain checkbox under the hood (so screen readers/keyboard
 * behave exactly like a native control) with the app's own "pill"
 * visual language layered on, since no shared Switch primitive exists
 * elsewhere in the app yet and six uses on a single page doesn't
 * justify extracting one. */
function ToggleRow({ id, label, description, checked, disabled, onChange }: ToggleRowProps) {
  return (
    <div className="flex items-start justify-between gap-4 px-5 py-4">
      <div className="min-w-0">
        <label htmlFor={id} className="text-sm font-medium text-slate-800">
          {label}
        </label>
        <p className="mt-0.5 text-xs text-slate-500">{description}</p>
      </div>
      <button
        type="button"
        id={id}
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={`relative mt-0.5 inline-flex h-6 w-11 shrink-0 items-center rounded-full transition disabled:cursor-not-allowed disabled:opacity-50 ${
          checked ? "bg-slate-900" : "bg-slate-200"
        }`}
      >
        <span
          className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition ${
            checked ? "translate-x-6" : "translate-x-1"
          }`}
        />
      </button>
    </div>
  );
}

export default function PlatformSettingsPage() {
  const { t } = useTranslation();
  const toast = useToast();
  const [data, setData] = useState<PlatformSettings | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  // Set only from a 409 platform_settings_version_conflict response --
  // never touches draft/data itself (see handleConfirmSave), so the
  // user's unsaved values are still exactly what they were when this
  // dialog opens. reloading is separate from `submitting`: a version
  // conflict already closed the save dialog, so "Reload latest
  // settings" needs its own pending state for its own button.
  const [conflictVersion, setConflictVersion] = useState<number | null>(null);
  const [reloading, setReloading] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const load = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);
    setError(null);
    try {
      const json = await apiFetch<PlatformSettings>("/admin/settings", { signal: controller.signal });
      setData(json);
      setDraft(draftFromData(json));
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") return;
      setData(null);
      setDraft(null);
      setError(e instanceof ApiError ? e.message : GENERIC_LOAD_ERROR);
    } finally {
      if (abortRef.current === controller) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    return () => abortRef.current?.abort();
  }, [load]);

  const changes = useMemo<SettingsFieldChange[]>(() => {
    if (!data || !draft) return [];
    const labelFor: Record<EditableField, string> = {
      maintenance_mode: t("admin.maintenanceModeLabel"),
      registrations_enabled: t("admin.registrationsEnabledLabel"),
      ai_enabled: t("admin.aiEnabledLabel"),
      emails_enabled: t("admin.emailsEnabledLabel"),
      invoice_reminders_enabled: t("admin.invoiceRemindersEnabledLabel"),
      quote_reminders_enabled: t("admin.quoteRemindersEnabledLabel"),
      default_language: t("admin.defaultLanguageLabel"),
      default_currency: t("admin.defaultCurrencyLabel"),
    };
    const displayFor = (field: EditableField, value: boolean | string): string => {
      if (field === "default_language") return LANGUAGE_LABELS[value as Language] ?? String(value);
      if (field === "default_currency") return getCurrencyLabel(t, value as CurrencyCode);
      return value ? t("common.enabled") : t("common.disabled");
    };
    const fields = Object.keys(labelFor) as EditableField[];
    const result: SettingsFieldChange[] = [];
    for (const field of fields) {
      if (data[field] === draft[field]) continue;
      result.push({
        field,
        label: labelFor[field],
        oldDisplay: displayFor(field, data[field]),
        newDisplay: displayFor(field, draft[field]),
        warningKey: warningKeyFor(field, draft[field]),
      });
    }
    return result;
  }, [data, draft, t]);

  function updateDraft<K extends EditableField>(field: K, value: Draft[K]) {
    setDraft((prev) => (prev ? { ...prev, [field]: value } : prev));
  }

  function discardChanges() {
    if (data) setDraft(draftFromData(data));
  }

  async function handleConfirmSave(reason: string) {
    if (changes.length === 0 || !data) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const body: PlatformSettingsUpdateRequest = { reason, expected_version: data.version };
      for (const change of changes) {
        (body as Record<string, unknown>)[change.field] = draft?.[change.field];
      }
      // The mutation response IS the refreshed, effective settings --
      // never an optimistic local update, and the source of truth for
      // both `data` and the draft it's reset to.
      const updated = await apiFetch<PlatformSettings>("/admin/settings", {
        method: "PATCH",
        body: JSON.stringify(body),
      });
      setData(updated);
      setDraft(draftFromData(updated));
      setDialogOpen(false);
      toast.success(t("admin.settingsSavedToast"));
    } catch (e) {
      const code = getApiErrorCode(e);
      if (code === "platform_settings_version_conflict") {
        // Never overwrite the user's unsaved draft here -- draft/data
        // are left untouched. Close the save dialog and hand off to the
        // dedicated conflict dialog, which is the only place that may
        // discard the draft, and only on an explicit user click.
        const currentVersion =
          e instanceof ApiError && e.body && typeof e.body === "object" && "detail" in e.body
            ? ((e.body as { detail?: { current_version?: unknown } }).detail?.current_version as number | undefined)
            : undefined;
        setDialogOpen(false);
        setConflictVersion(currentVersion ?? data.version + 1);
      } else if (code === "no_changes") {
        setSubmitError(t("admin.errorSettingsNoChanges"));
      } else {
        setSubmitError(e instanceof ApiError ? formatApiError(e, t("admin.mutationErrorGeneric")) : t("admin.mutationErrorGeneric"));
      }
    } finally {
      setSubmitting(false);
    }
  }

  async function handleReloadLatest() {
    setReloading(true);
    try {
      const updated = await apiFetch<PlatformSettings>("/admin/settings");
      setData(updated);
      setDraft(draftFromData(updated));
      setConflictVersion(null);
      toast.success(t("admin.settingsReloadedToast"));
    } catch (e) {
      toast.error(e instanceof ApiError ? formatApiError(e, t("admin.mutationErrorGeneric")) : t("admin.mutationErrorGeneric"));
    } finally {
      setReloading(false);
    }
  }

  const shownOrigins = data?.cors_allowed_origins.slice(0, MAX_ORIGINS_SHOWN) ?? [];
  const extraOriginsCount = data ? Math.max(0, data.cors_allowed_origins.length - MAX_ORIGINS_SHOWN) : 0;
  const hasUnsavedChanges = changes.length > 0;

  return (
    <div className="mx-auto max-w-3xl space-y-6 pb-24">
      <PageHeader
        title={t("admin.settingsTitle")}
        subtitle={t("admin.settingsSubtitle")}
        actions={
          <Button type="button" variant="secondary" size="sm" onClick={() => void load()} disabled={loading}>
            {loading ? t("common.refreshing") : t("common.refresh")}
          </Button>
        }
      />

      {error ? (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800" role="alert">
          {error === GENERIC_LOAD_ERROR ? t("admin.loadError") : error}
        </div>
      ) : null}

      {data?.maintenance_mode ? (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800" role="status">
          {t("admin.maintenanceModeActiveBanner")}
        </div>
      ) : null}

      {draft && !loading ? (
        <>
          <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
            <h2 className="border-b border-slate-100 px-5 py-3 text-sm font-semibold text-slate-900">
              {t("admin.sectionPlatformAccess")}
            </h2>
            <div className="divide-y divide-slate-100">
              <ToggleRow
                id="setting-maintenance-mode"
                label={t("admin.maintenanceModeLabel")}
                description={t("admin.maintenanceModeDescription")}
                checked={draft.maintenance_mode}
                disabled={submitting}
                onChange={(next) => updateDraft("maintenance_mode", next)}
              />
              <ToggleRow
                id="setting-registrations-enabled"
                label={t("admin.registrationsEnabledLabel")}
                description={t("admin.registrationsEnabledDescription")}
                checked={draft.registrations_enabled}
                disabled={submitting}
                onChange={(next) => updateDraft("registrations_enabled", next)}
              />
            </div>
          </section>

          <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
            <h2 className="border-b border-slate-100 px-5 py-3 text-sm font-semibold text-slate-900">
              {t("admin.sectionFeatures")}
            </h2>
            <div className="divide-y divide-slate-100">
              <ToggleRow
                id="setting-ai-enabled"
                label={t("admin.aiEnabledLabel")}
                description={t("admin.aiEnabledDescription")}
                checked={draft.ai_enabled}
                disabled={submitting}
                onChange={(next) => updateDraft("ai_enabled", next)}
              />
            </div>
          </section>

          <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
            <h2 className="border-b border-slate-100 px-5 py-3 text-sm font-semibold text-slate-900">
              {t("admin.sectionNotifications")}
            </h2>
            <div className="divide-y divide-slate-100">
              <ToggleRow
                id="setting-emails-enabled"
                label={t("admin.emailsEnabledLabel")}
                description={t("admin.emailsEnabledDescription")}
                checked={draft.emails_enabled}
                disabled={submitting}
                onChange={(next) => updateDraft("emails_enabled", next)}
              />
              <ToggleRow
                id="setting-invoice-reminders-enabled"
                label={t("admin.invoiceRemindersEnabledLabel")}
                description={t("admin.invoiceRemindersEnabledDescription")}
                checked={draft.invoice_reminders_enabled}
                disabled={submitting}
                onChange={(next) => updateDraft("invoice_reminders_enabled", next)}
              />
              <ToggleRow
                id="setting-quote-reminders-enabled"
                label={t("admin.quoteRemindersEnabledLabel")}
                description={t("admin.quoteRemindersEnabledDescription")}
                checked={draft.quote_reminders_enabled}
                disabled={submitting}
                onChange={(next) => updateDraft("quote_reminders_enabled", next)}
              />
            </div>
          </section>

          <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
            <h2 className="border-b border-slate-100 px-5 py-3 text-sm font-semibold text-slate-900">
              {t("admin.sectionDefaults")}
            </h2>
            <p className="px-5 pt-3 text-xs text-slate-500">{t("admin.defaultsNote")}</p>
            <div className="grid gap-4 px-5 py-4 sm:grid-cols-2">
              <div>
                <label htmlFor="setting-default-language" className="text-sm font-medium text-slate-700">
                  {t("admin.defaultLanguageLabel")}
                </label>
                <Select
                  id="setting-default-language"
                  className="mt-1"
                  value={draft.default_language}
                  disabled={submitting}
                  onChange={(e) => updateDraft("default_language", e.target.value)}
                >
                  {LANGUAGES.map((code) => (
                    <option key={code} value={code}>
                      {LANGUAGE_LABELS[code]}
                    </option>
                  ))}
                </Select>
              </div>
              <div>
                <label htmlFor="setting-default-currency" className="text-sm font-medium text-slate-700">
                  {t("admin.defaultCurrencyLabel")}
                </label>
                <Select
                  id="setting-default-currency"
                  className="mt-1"
                  value={draft.default_currency}
                  disabled={submitting}
                  onChange={(e) => updateDraft("default_currency", e.target.value)}
                >
                  {CURRENCY_CODES.map((code) => (
                    <option key={code} value={code}>
                      {getCurrencyLabel(t, code)}
                    </option>
                  ))}
                </Select>
              </div>
            </div>
          </section>
        </>
      ) : null}

      <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        <h2 className="border-b border-slate-100 px-5 py-3 text-sm font-semibold text-slate-900">
          {t("admin.sectionInfrastructureStatus")}
        </h2>
        <dl className="divide-y divide-slate-100">
          <div className="flex items-center justify-between gap-4 px-5 py-4">
            <dt className="text-sm font-medium text-slate-700">{t("admin.aiProviderLabel")}</dt>
            <dd>
              {loading ? (
                <span className="inline-flex h-6 w-24 animate-pulse rounded-full bg-slate-100" aria-hidden />
              ) : (
                <span className="text-sm text-slate-900">{data?.ai_provider ?? t("admin.notConfiguredValue")}</span>
              )}
            </dd>
          </div>
          <div className="flex items-center justify-between gap-4 px-5 py-4">
            <dt className="text-sm font-medium text-slate-700">{t("admin.emailProviderLabel")}</dt>
            <dd>
              {loading ? (
                <span className="inline-flex h-6 w-24 animate-pulse rounded-full bg-slate-100" aria-hidden />
              ) : (
                <span className="text-sm text-slate-900">{data?.email_provider ?? t("admin.notConfiguredValue")}</span>
              )}
            </dd>
          </div>
          <div className="flex items-start justify-between gap-4 px-5 py-4">
            <dt className="text-sm font-medium text-slate-700">{t("admin.corsOriginsLabel")}</dt>
            <dd className="flex max-w-xs flex-wrap justify-end gap-1.5">
              {loading ? (
                <span className="inline-flex h-6 w-32 animate-pulse rounded-full bg-slate-100" aria-hidden />
              ) : shownOrigins.length === 0 ? (
                <span className="text-sm text-slate-500">{t("admin.corsOriginsEmpty")}</span>
              ) : (
                <>
                  {shownOrigins.map((origin) => (
                    <Badge key={origin} className="bg-slate-100 text-slate-700 ring-slate-200">
                      {origin}
                    </Badge>
                  ))}
                  {extraOriginsCount > 0 ? (
                    <Badge className="bg-slate-100 text-slate-500 ring-slate-200">
                      {t("admin.corsOriginsMore", { count: extraOriginsCount })}
                    </Badge>
                  ) : null}
                </>
              )}
            </dd>
          </div>
        </dl>
      </section>

      {data ? <p className="text-xs text-slate-400">{t("admin.settingsVersionDiagnostic", { version: data.version })}</p> : null}

      {hasUnsavedChanges ? (
        <div className="fixed inset-x-0 bottom-0 z-40 border-t border-slate-200 bg-white/95 px-4 py-3 backdrop-blur">
          <div className="mx-auto flex max-w-3xl flex-wrap items-center justify-between gap-3">
            <p className="text-sm text-slate-600">{t("admin.unsavedChangesSummary", { count: changes.length })}</p>
            <div className="flex gap-2">
              <Button type="button" variant="secondary" size="sm" onClick={discardChanges} disabled={submitting}>
                {t("admin.discardChangesButton")}
              </Button>
              <Button type="button" size="sm" onClick={() => setDialogOpen(true)} disabled={submitting}>
                {t("admin.reviewAndSaveButton")}
              </Button>
            </div>
          </div>
        </div>
      ) : null}

      <SettingsChangeDialog
        open={dialogOpen}
        changes={changes}
        submitting={submitting}
        error={submitError}
        onClose={() => {
          if (!submitting) {
            setDialogOpen(false);
            setSubmitError(null);
          }
        }}
        onConfirm={(reason) => void handleConfirmSave(reason)}
      />

      <VersionConflictDialog
        open={conflictVersion !== null}
        reloading={reloading}
        onReload={() => void handleReloadLatest()}
        onCancel={() => setConflictVersion(null)}
      />
    </div>
  );
}
