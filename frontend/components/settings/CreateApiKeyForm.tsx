"use client";

import { FormEvent, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { PlanLimitReachedDialog } from "@/components/ui/PlanLimitReachedDialog";
import { useToast } from "@/components/ui/toast";
import { apiFetch, orgPath } from "@/lib/api";
import { formatApiError, getPlanLimitReachedDetail, isEmailNotVerifiedError } from "@/lib/format-api-error";
import { API_KEY_PERMISSIONS, getApiKeyPermissionLabel, type ApiKeyPermission } from "@/lib/api-key-permissions";
import { useTranslation } from "@/lib/i18n/useTranslation";
import type { ApiKeyCreated, PlanLimitReachedDetail } from "@/lib/types";

const NAME_MAX_LENGTH = 100;
const DESCRIPTION_MAX_LENGTH = 500;

type CreateApiKeyFormProps = {
  onCreated: (created: ApiKeyCreated) => void;
};

export function CreateApiKeyForm({ onCreated }: CreateApiKeyFormProps) {
  const toast = useToast();
  const { t } = useTranslation();

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [permissions, setPermissions] = useState<Set<ApiKeyPermission>>(new Set());
  const [expiresAt, setExpiresAt] = useState("");
  const [nameError, setNameError] = useState<string | null>(null);
  const [permissionsError, setPermissionsError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [planLimitDetail, setPlanLimitDetail] = useState<PlanLimitReachedDetail | null>(null);

  function togglePermission(permission: ApiKeyPermission) {
    setPermissions((prev) => {
      const next = new Set(prev);
      if (next.has(permission)) next.delete(permission);
      else next.add(permission);
      return next;
    });
  }

  function resetForm() {
    setName("");
    setDescription("");
    setPermissions(new Set());
    setExpiresAt("");
    setNameError(null);
    setPermissionsError(null);
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();

    const trimmedName = name.trim();
    let hasError = false;
    if (!trimmedName) {
      setNameError(t("common.errorRequired", { field: t("apiKeys.nameLabel") }));
      hasError = true;
    } else {
      setNameError(null);
    }
    if (permissions.size === 0) {
      setPermissionsError(t("apiKeys.errorPermissionsRequired"));
      hasError = true;
    } else {
      setPermissionsError(null);
    }
    if (hasError) return;

    const loadingId = toast.loading(t("apiKeys.toastCreating"));
    setIsSubmitting(true);
    try {
      const created = await apiFetch<ApiKeyCreated>(orgPath("api-keys"), {
        method: "POST",
        body: JSON.stringify({
          name: trimmedName,
          description: description.trim(),
          permissions: Array.from(permissions),
          expires_at: expiresAt ? new Date(expiresAt).toISOString() : null,
        }),
      });
      toast.dismiss(loadingId);
      toast.success(t("apiKeys.toastCreated"));
      resetForm();
      onCreated(created);
    } catch (err) {
      toast.dismiss(loadingId);
      const planLimit = getPlanLimitReachedDetail(err);
      if (planLimit) {
        setPlanLimitDetail(planLimit);
      } else {
        toast.error(
          isEmailNotVerifiedError(err)
            ? t("errors.emailNotVerified")
            : formatApiError(err, t("apiKeys.toastCreateError"))
        );
      }
    } finally {
      setIsSubmitting(false);
    }
  }

  const disabled = isSubmitting;

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-6">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">{t("apiKeys.createTitle")}</h2>
      <p className="mt-1 text-sm text-slate-500">{t("apiKeys.createSubtitle")}</p>

      <form onSubmit={(e) => void handleSubmit(e)} className="mt-4 space-y-4" noValidate>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <label htmlFor="apikey-name" className="text-sm font-medium text-slate-700">
              {t("apiKeys.nameLabel")} <span className="text-red-600">*</span>
            </label>
            <Input
              id="apikey-name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={disabled}
              maxLength={NAME_MAX_LENGTH}
              placeholder={t("apiKeys.namePlaceholder")}
              className="mt-1"
              aria-invalid={Boolean(nameError)}
              aria-describedby={nameError ? "apikey-name-err" : undefined}
            />
            {nameError ? (
              <p id="apikey-name-err" className="mt-1 text-xs text-red-600" role="alert">
                {nameError}
              </p>
            ) : null}
          </div>

          <div>
            <label htmlFor="apikey-expires" className="text-sm font-medium text-slate-700">
              {t("apiKeys.expiresAtLabel")}
            </label>
            <Input
              id="apikey-expires"
              type="date"
              value={expiresAt}
              onChange={(e) => setExpiresAt(e.target.value)}
              disabled={disabled}
              min={new Date().toISOString().slice(0, 10)}
              className="mt-1"
            />
            <p className="mt-1 text-xs text-slate-500">{t("apiKeys.expiresAtHelp")}</p>
          </div>

          <div className="sm:col-span-2">
            <label htmlFor="apikey-description" className="text-sm font-medium text-slate-700">
              {t("apiKeys.descriptionLabel")}
            </label>
            <Input
              id="apikey-description"
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              disabled={disabled}
              maxLength={DESCRIPTION_MAX_LENGTH}
              placeholder={t("apiKeys.descriptionPlaceholder")}
              className="mt-1"
            />
          </div>
        </div>

        <fieldset>
          <legend className="text-sm font-medium text-slate-700">
            {t("apiKeys.permissionsLabel")} <span className="text-red-600">*</span>
          </legend>
          <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-3">
            {API_KEY_PERMISSIONS.map((permission) => (
              <label key={permission} className="flex items-center gap-2 text-sm text-slate-700">
                <input
                  type="checkbox"
                  checked={permissions.has(permission)}
                  onChange={() => togglePermission(permission)}
                  disabled={disabled}
                  className="h-4 w-4 rounded border-slate-300 text-slate-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-400"
                />
                {getApiKeyPermissionLabel(t, permission)}
              </label>
            ))}
          </div>
          {permissionsError ? (
            <p className="mt-1 text-xs text-red-600" role="alert">
              {permissionsError}
            </p>
          ) : null}
        </fieldset>

        <div className="flex justify-end pt-1">
          <Button type="submit" disabled={disabled}>
            {isSubmitting ? t("common.saving") : t("apiKeys.createButton")}
          </Button>
        </div>
      </form>
      <PlanLimitReachedDialog detail={planLimitDetail} onClose={() => setPlanLimitDetail(null)} />
    </section>
  );
}
