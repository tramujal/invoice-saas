"use client";

import { FormEvent, useEffect, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Input, Textarea } from "@/components/ui/Input";
import { PlanLimitReachedDialog } from "@/components/ui/PlanLimitReachedDialog";
import { useToast } from "@/components/ui/toast";
import { apiFetch, orgPath } from "@/lib/api";
import { formatApiError, getPlanLimitReachedDetail, isEmailNotVerifiedError } from "@/lib/format-api-error";
import { useTranslation } from "@/lib/i18n/useTranslation";
import type { TranslateFn } from "@/lib/i18n/useTranslation";
import type { Customer, PlanLimitReachedDetail } from "@/lib/types";

const LIMITS = {
  name: 255,
  email: 255,
  phone: 64,
  address: 512,
  tax_id: 64,
} as const;

type FieldKey = keyof typeof LIMITS;
type FieldErrors = Partial<Record<FieldKey, string>>;

function simpleEmailValid(email: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
}

function validate(
  t: TranslateFn,
  params: {
    name: string;
    email: string;
    phone: string;
    address: string;
    taxId: string;
  }
): FieldErrors | null {
  const errors: FieldErrors = {};
  const name = params.name.trim();
  const email = params.email.trim();
  const phone = params.phone.trim();
  const address = params.address.trim();
  const taxId = params.taxId.trim();

  if (!name) errors.name = t("common.errorRequired", { field: t("common.name") });
  else if (name.length > LIMITS.name)
    errors.name = t("common.errorMaxLength", { field: t("common.name"), max: LIMITS.name });

  if (!email) errors.email = t("common.errorRequired", { field: t("common.email") });
  else if (email.length > LIMITS.email)
    errors.email = t("common.errorMaxLength", { field: t("common.email"), max: LIMITS.email });
  else if (!simpleEmailValid(email)) errors.email = t("common.errorInvalidEmail");

  if (phone.length > LIMITS.phone)
    errors.phone = t("common.errorMaxLength", { field: t("common.phone"), max: LIMITS.phone });

  if (address.length > LIMITS.address)
    errors.address = t("common.errorMaxLength", {
      field: t("common.address"),
      max: LIMITS.address,
    });

  if (taxId.length > LIMITS.tax_id)
    errors.tax_id = t("common.errorMaxLength", {
      field: t("customers.taxIdLabel"),
      max: LIMITS.tax_id,
    });

  return Object.keys(errors).length > 0 ? errors : null;
}

type CustomerFormProps = {
  /** When given, the form edits this customer (PATCH); otherwise it
   * creates a new one (POST) -- mirrors ProductForm's exact shape. */
  customer?: Customer | null;
  onSaved: () => void | Promise<void>;
  onCancel?: () => void;
};

export function CustomerForm({ customer, onSaved, onCancel }: CustomerFormProps) {
  const toast = useToast();
  const { t } = useTranslation();
  const isEditing = Boolean(customer);

  const [name, setName] = useState(customer?.name ?? "");
  const [email, setEmail] = useState(customer?.email ?? "");
  const [phone, setPhone] = useState(customer?.phone ?? "");
  const [address, setAddress] = useState(customer?.address ?? "");
  const [taxId, setTaxId] = useState(customer?.tax_id ?? "");
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [planLimitDetail, setPlanLimitDetail] = useState<PlanLimitReachedDetail | null>(null);

  useEffect(() => {
    setName(customer?.name ?? "");
    setEmail(customer?.email ?? "");
    setPhone(customer?.phone ?? "");
    setAddress(customer?.address ?? "");
    setTaxId(customer?.tax_id ?? "");
    setFieldErrors({});
  }, [customer]);

  function resetForm() {
    setName("");
    setEmail("");
    setPhone("");
    setAddress("");
    setTaxId("");
    setFieldErrors({});
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();

    const errs = validate(t, { name, email, phone, address, taxId });
    if (errs) {
      setFieldErrors(errs);
      return;
    }
    setFieldErrors({});

    const payload = {
      name: name.trim(),
      email: email.trim(),
      phone: phone.trim(),
      address: address.trim(),
      tax_id: taxId.trim(),
    };

    const loadingId = toast.loading(
      isEditing ? t("customers.toastSaving") : t("customers.toastCreating")
    );
    setIsSubmitting(true);
    try {
      if (isEditing && customer) {
        await apiFetch<Customer>(orgPath(`customers/${customer.id}`), {
          method: "PATCH",
          body: JSON.stringify(payload),
        });
        toast.dismiss(loadingId);
        toast.success(t("customers.toastSaved"));
      } else {
        await apiFetch<Customer>(orgPath("customers"), {
          method: "POST",
          body: JSON.stringify(payload),
        });
        toast.dismiss(loadingId);
        toast.success(t("customers.toastCreated"));
        resetForm();
      }
      await onSaved();
    } catch (err) {
      toast.dismiss(loadingId);
      const planLimit = getPlanLimitReachedDetail(err);
      if (planLimit) {
        setPlanLimitDetail(planLimit);
      } else {
        toast.error(
          isEmailNotVerifiedError(err)
            ? t("errors.emailNotVerified")
            : formatApiError(
                err,
                isEditing ? t("customers.toastSaveError") : t("customers.toastCreateError")
              )
        );
      }
    } finally {
      setIsSubmitting(false);
    }
  }

  const disabled = isSubmitting;

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-6">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
        {isEditing ? t("customers.editTitle") : t("customers.addTitle")}
      </h2>
      <p className="mt-1 text-sm text-slate-500">
        {isEditing ? t("customers.editSubtitle") : t("customers.addSubtitle")}
      </p>

      <form onSubmit={(e) => void handleSubmit(e)} className="mt-5 space-y-4" noValidate>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="sm:col-span-2">
            <label htmlFor="cust-name" className="text-sm font-medium text-slate-700">
              {t("common.name")} <span className="text-red-600">*</span>
            </label>
            <Input
              id="cust-name"
              type="text"
              name="name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={disabled}
              maxLength={LIMITS.name}
              autoComplete="name"
              className="mt-1"
              aria-invalid={Boolean(fieldErrors.name)}
              aria-describedby={fieldErrors.name ? "cust-name-err" : undefined}
            />
            {fieldErrors.name ? (
              <p id="cust-name-err" className="mt-1 text-xs text-red-600" role="alert">
                {fieldErrors.name}
              </p>
            ) : null}
          </div>

          <div className="sm:col-span-2">
            <label htmlFor="cust-email" className="text-sm font-medium text-slate-700">
              {t("common.email")} <span className="text-red-600">*</span>
            </label>
            <Input
              id="cust-email"
              type="email"
              name="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              disabled={disabled}
              maxLength={LIMITS.email}
              autoComplete="email"
              className="mt-1"
              aria-invalid={Boolean(fieldErrors.email)}
              aria-describedby={fieldErrors.email ? "cust-email-err" : undefined}
            />
            {fieldErrors.email ? (
              <p id="cust-email-err" className="mt-1 text-xs text-red-600" role="alert">
                {fieldErrors.email}
              </p>
            ) : null}
          </div>

          <div className="grid grid-cols-1 gap-4 sm:col-span-2 md:grid-cols-2">
            <div>
              <label htmlFor="cust-phone" className="text-sm font-medium text-slate-700">
                {t("common.phone")}
              </label>
              <Input
                id="cust-phone"
                type="tel"
                name="phone"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                disabled={disabled}
                maxLength={LIMITS.phone}
                autoComplete="tel"
                className="mt-1"
                aria-invalid={Boolean(fieldErrors.phone)}
                aria-describedby={fieldErrors.phone ? "cust-phone-err" : undefined}
              />
              {fieldErrors.phone ? (
                <p id="cust-phone-err" className="mt-1 text-xs text-red-600" role="alert">
                  {fieldErrors.phone}
                </p>
              ) : null}
            </div>

            <div>
              <label htmlFor="cust-address" className="text-sm font-medium text-slate-700">
                {t("common.address")}
              </label>
              <Textarea
                id="cust-address"
                name="address"
                value={address}
                onChange={(e) => setAddress(e.target.value)}
                disabled={disabled}
                maxLength={LIMITS.address}
                rows={3}
                className="mt-1 resize-y"
                aria-invalid={Boolean(fieldErrors.address)}
                aria-describedby={fieldErrors.address ? "cust-address-err" : undefined}
              />
              {fieldErrors.address ? (
                <p id="cust-address-err" className="mt-1 text-xs text-red-600" role="alert">
                  {fieldErrors.address}
                </p>
              ) : null}
            </div>

            <div>
              <label htmlFor="cust-tax-id" className="text-sm font-medium text-slate-700">
                {t("customers.taxIdLabel")}
              </label>
              <Input
                id="cust-tax-id"
                type="text"
                name="tax_id"
                value={taxId}
                onChange={(e) => setTaxId(e.target.value)}
                disabled={disabled}
                maxLength={LIMITS.tax_id}
                className="mt-1"
                aria-invalid={Boolean(fieldErrors.tax_id)}
                aria-describedby={fieldErrors.tax_id ? "cust-tax-id-err" : undefined}
              />
              {fieldErrors.tax_id ? (
                <p id="cust-tax-id-err" className="mt-1 text-xs text-red-600" role="alert">
                  {fieldErrors.tax_id}
                </p>
              ) : null}
            </div>
          </div>
        </div>

        <div className="flex flex-col-reverse gap-2 pt-1 sm:flex-row sm:justify-end">
          <Button
            type="button"
            variant="secondary"
            disabled={disabled}
            onClick={() => (isEditing ? onCancel?.() : resetForm())}
          >
            {isEditing ? t("common.cancel") : t("common.clear")}
          </Button>
          <Button type="submit" disabled={disabled}>
            {isSubmitting ? (
              <>
                <svg
                  className="h-4 w-4 shrink-0 animate-spin"
                  xmlns="http://www.w3.org/2000/svg"
                  fill="none"
                  viewBox="0 0 24 24"
                  aria-hidden
                >
                  <circle
                    className="opacity-25"
                    cx="12"
                    cy="12"
                    r="10"
                    stroke="currentColor"
                    strokeWidth="4"
                  />
                  <path
                    className="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                  />
                </svg>
                {t("common.saving")}
              </>
            ) : isEditing ? (
              t("common.saveChanges")
            ) : (
              t("customers.createButton")
            )}
          </Button>
        </div>
      </form>

      <PlanLimitReachedDialog detail={planLimitDetail} onClose={() => setPlanLimitDetail(null)} />
    </section>
  );
}
