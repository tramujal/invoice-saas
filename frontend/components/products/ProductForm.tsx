"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";

import { useToast } from "@/components/ui/toast";
import { apiFetch, orgPath } from "@/lib/api";
import { formatApiError, isEmailNotVerifiedError } from "@/lib/format-api-error";
import { useTranslation } from "@/lib/i18n/useTranslation";
import type { TranslateFn } from "@/lib/i18n/useTranslation";
import { CURRENCY_CODES, getCurrencyLabel, type CurrencyCode } from "@/lib/organization-settings";
import { PRODUCT_TYPES, getProductTypeLabel, type ProductType } from "@/lib/product-type";
import type { Product } from "@/lib/types";

const LIMITS = {
  name: 255,
  description: 1024,
  sku: 64,
} as const;

type FieldKey = keyof typeof LIMITS;
type FieldErrors = Partial<Record<FieldKey, string>>;

function validate(
  t: TranslateFn,
  params: { name: string; description: string; sku: string }
): FieldErrors | null {
  const errors: FieldErrors = {};
  const name = params.name.trim();

  if (!name) errors.name = t("common.errorRequired", { field: t("common.name") });
  else if (name.length > LIMITS.name)
    errors.name = t("common.errorMaxLength", { field: t("common.name"), max: LIMITS.name });

  if (params.description.length > LIMITS.description)
    errors.description = t("common.errorMaxLength", {
      field: t("products.descriptionLabel"),
      max: LIMITS.description,
    });

  if (params.sku.length > LIMITS.sku)
    errors.sku = t("common.errorMaxLength", { field: t("products.skuLabel"), max: LIMITS.sku });

  return Object.keys(errors).length > 0 ? errors : null;
}

type ProductFormProps = {
  /** When given, the form edits this product (PATCH); otherwise it
   * creates a new one (POST). */
  product?: Product | null;
  onSaved: () => void | Promise<void>;
  onCancel?: () => void;
};

export function ProductForm({ product, onSaved, onCancel }: ProductFormProps) {
  const toast = useToast();
  const { t } = useTranslation();
  const isEditing = Boolean(product);

  const [name, setName] = useState(product?.name ?? "");
  const [description, setDescription] = useState(product?.description ?? "");
  const [type, setType] = useState<ProductType>(product?.type ?? "service");
  const [sku, setSku] = useState(product?.sku ?? "");
  const [unitPrice, setUnitPrice] = useState(product?.default_unit_price ?? "0");
  const [currencyCode, setCurrencyCode] = useState<CurrencyCode>(
    (product?.currency_code as CurrencyCode) ?? "USD"
  );
  const [taxPercent, setTaxPercent] = useState(() =>
    product ? String(Number(product.default_tax_rate) * 100) : "0"
  );
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    setName(product?.name ?? "");
    setDescription(product?.description ?? "");
    setType(product?.type ?? "service");
    setSku(product?.sku ?? "");
    setUnitPrice(product?.default_unit_price ?? "0");
    setCurrencyCode((product?.currency_code as CurrencyCode) ?? "USD");
    setTaxPercent(product ? String(Number(product.default_tax_rate) * 100) : "0");
    setFieldErrors({});
  }, [product]);

  const taxRateFraction = useMemo(() => {
    const p = Number(taxPercent);
    if (!Number.isFinite(p) || p < 0) return 0;
    return Math.min(p, 100) / 100;
  }, [taxPercent]);

  function resetForm() {
    setName("");
    setDescription("");
    setType("service");
    setSku("");
    setUnitPrice("0");
    setCurrencyCode("USD");
    setTaxPercent("0");
    setFieldErrors({});
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();

    const errs = validate(t, { name, description, sku });
    if (errs) {
      setFieldErrors(errs);
      return;
    }
    setFieldErrors({});

    const price = Number(unitPrice);
    if (!Number.isFinite(price) || price < 0) {
      toast.error(t("products.errorInvalidPrice"));
      return;
    }

    const payload = {
      name: name.trim(),
      description: description.trim(),
      type,
      sku: sku.trim(),
      default_unit_price: price,
      currency_code: currencyCode,
      default_tax_rate: taxRateFraction,
    };

    const loadingId = toast.loading(
      isEditing ? t("products.toastSaving") : t("products.toastCreating")
    );
    setIsSubmitting(true);
    try {
      if (isEditing && product) {
        await apiFetch<Product>(orgPath(`products/${product.id}`), {
          method: "PATCH",
          body: JSON.stringify(payload),
        });
        toast.dismiss(loadingId);
        toast.success(t("products.toastSaved"));
      } else {
        await apiFetch<Product>(orgPath("products"), {
          method: "POST",
          body: JSON.stringify(payload),
        });
        toast.dismiss(loadingId);
        toast.success(t("products.toastCreated"));
        resetForm();
      }
      await onSaved();
    } catch (err) {
      toast.dismiss(loadingId);
      toast.error(
        isEmailNotVerifiedError(err)
          ? t("errors.emailNotVerified")
          : formatApiError(
              err,
              isEditing ? t("products.toastSaveError") : t("products.toastCreateError")
            )
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  const disabled = isSubmitting;

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-6">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
        {isEditing ? t("products.editTitle") : t("products.addTitle")}
      </h2>
      <p className="mt-1 text-sm text-slate-500">
        {isEditing ? t("products.editSubtitle") : t("products.addSubtitle")}
      </p>

      <form onSubmit={(e) => void handleSubmit(e)} className="mt-5 space-y-4" noValidate>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="sm:col-span-2">
            <label htmlFor="prod-name" className="text-sm font-medium text-slate-700">
              {t("common.name")} <span className="text-red-600">*</span>
            </label>
            <input
              id="prod-name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={disabled}
              maxLength={LIMITS.name}
              className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none ring-slate-400 focus:ring-2 disabled:bg-slate-50"
              aria-invalid={Boolean(fieldErrors.name)}
              aria-describedby={fieldErrors.name ? "prod-name-err" : undefined}
            />
            {fieldErrors.name ? (
              <p id="prod-name-err" className="mt-1 text-xs text-red-600" role="alert">
                {fieldErrors.name}
              </p>
            ) : null}
          </div>

          <div className="sm:col-span-2">
            <label htmlFor="prod-description" className="text-sm font-medium text-slate-700">
              {t("products.descriptionLabel")}
            </label>
            <textarea
              id="prod-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              disabled={disabled}
              maxLength={LIMITS.description}
              rows={2}
              className="mt-1 w-full resize-y rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none ring-slate-400 focus:ring-2 disabled:bg-slate-50"
              aria-invalid={Boolean(fieldErrors.description)}
              aria-describedby={fieldErrors.description ? "prod-description-err" : undefined}
            />
            {fieldErrors.description ? (
              <p id="prod-description-err" className="mt-1 text-xs text-red-600" role="alert">
                {fieldErrors.description}
              </p>
            ) : null}
          </div>

          <div>
            <label htmlFor="prod-type" className="text-sm font-medium text-slate-700">
              {t("products.typeLabel")}
            </label>
            <select
              id="prod-type"
              value={type}
              onChange={(e) => setType(e.target.value as ProductType)}
              disabled={disabled}
              className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none ring-slate-400 focus:ring-2 disabled:bg-slate-50"
            >
              {PRODUCT_TYPES.map((option) => (
                <option key={option} value={option}>
                  {getProductTypeLabel(t, option)}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label htmlFor="prod-sku" className="text-sm font-medium text-slate-700">
              {t("products.skuLabel")}
            </label>
            <input
              id="prod-sku"
              type="text"
              value={sku}
              onChange={(e) => setSku(e.target.value)}
              disabled={disabled}
              maxLength={LIMITS.sku}
              className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none ring-slate-400 focus:ring-2 disabled:bg-slate-50"
              aria-invalid={Boolean(fieldErrors.sku)}
              aria-describedby={fieldErrors.sku ? "prod-sku-err" : undefined}
            />
            {fieldErrors.sku ? (
              <p id="prod-sku-err" className="mt-1 text-xs text-red-600" role="alert">
                {fieldErrors.sku}
              </p>
            ) : null}
          </div>

          <div>
            <label htmlFor="prod-price" className="text-sm font-medium text-slate-700">
              {t("products.defaultPriceLabel")}
            </label>
            <input
              id="prod-price"
              type="number"
              inputMode="decimal"
              min="0"
              step="0.01"
              value={unitPrice}
              onChange={(e) => setUnitPrice(e.target.value)}
              disabled={disabled}
              className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none ring-slate-400 focus:ring-2 disabled:bg-slate-50"
            />
          </div>

          <div>
            <label htmlFor="prod-currency" className="text-sm font-medium text-slate-700">
              {t("common.currencyLabel")}
            </label>
            <select
              id="prod-currency"
              value={currencyCode}
              onChange={(e) => setCurrencyCode(e.target.value as CurrencyCode)}
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
            <label htmlFor="prod-tax-rate" className="text-sm font-medium text-slate-700">
              {t("products.defaultTaxRateLabel")}
            </label>
            <input
              id="prod-tax-rate"
              type="number"
              inputMode="decimal"
              min="0"
              max="100"
              step="0.01"
              value={taxPercent}
              onChange={(e) => setTaxPercent(e.target.value)}
              disabled={disabled}
              className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none ring-slate-400 focus:ring-2 disabled:bg-slate-50"
            />
          </div>
        </div>

        <div className="flex flex-col-reverse gap-2 pt-1 sm:flex-row sm:justify-end">
          <button
            type="button"
            disabled={disabled}
            onClick={() => (isEditing ? onCancel?.() : resetForm())}
            className="rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium text-slate-800 shadow-sm hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isEditing ? t("common.cancel") : t("common.clear")}
          </button>
          <button
            type="submit"
            disabled={disabled}
            className="inline-flex items-center justify-center gap-2 rounded-lg bg-slate-900 px-5 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-70"
          >
            {isSubmitting
              ? t("common.saving")
              : isEditing
                ? t("common.saveChanges")
                : t("products.createButton")}
          </button>
        </div>
      </form>
    </section>
  );
}
