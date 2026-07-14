"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { useTranslation } from "@/lib/i18n/useTranslation";
import { parseQuantity, parseUnitPrice } from "@/lib/money";
import { CURRENCY_CODES, getCurrencyLabel, type CurrencyCode } from "@/lib/organization-settings";

type ManualLineEditorProps = {
  open: boolean;
  documentCurrency: CurrencyCode | null;
  defaultCurrency: CurrencyCode;
  onClose: () => void;
  onSubmit: (data: {
    currencyCode: CurrencyCode;
    description: string;
    quantity: string;
    unitPrice: string;
  }) => void;
};

export function ManualLineEditor({
  open,
  documentCurrency,
  defaultCurrency,
  onClose,
  onSubmit,
}: ManualLineEditorProps) {
  const { t } = useTranslation();
  const [mounted, setMounted] = useState(false);
  const [currencyCode, setCurrencyCode] = useState<CurrencyCode>(documentCurrency ?? defaultCurrency);
  const [description, setDescription] = useState("");
  const [quantity, setQuantity] = useState("1");
  const [unitPrice, setUnitPrice] = useState("0");
  const [error, setError] = useState<string | null>(null);
  const descriptionRef = useRef<HTMLInputElement>(null);

  useEffect(() => setMounted(true), []);

  useEffect(() => {
    if (!open) return;
    setCurrencyCode(documentCurrency ?? defaultCurrency);
    setDescription("");
    setQuantity("1");
    setUnitPrice("0");
    setError(null);
    descriptionRef.current?.focus();
  }, [open, documentCurrency, defaultCurrency]);

  useEffect(() => {
    if (!open) return;
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [open, onClose]);

  if (!open || !mounted) return null;

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = description.trim();
    if (!trimmed) {
      setError(t("lineItemPicker.errorDescriptionRequired"));
      return;
    }
    if (parseQuantity(quantity) === null) {
      setError(t("lineItemPicker.errorQuantityInvalid"));
      return;
    }
    if (parseUnitPrice(unitPrice) === null) {
      setError(t("lineItemPicker.errorUnitPriceInvalid"));
      return;
    }
    onSubmit({ currencyCode, description: trimmed, quantity, unitPrice });
  }

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t("lineItemPicker.manualLineTitle")}
        className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-5 shadow-xl"
      >
        <h2 className="text-sm font-semibold text-slate-900">
          {t("lineItemPicker.manualLineTitle")}
        </h2>

        <form onSubmit={handleSubmit} className="mt-4 space-y-4">
          <div>
            <label className="text-xs font-medium text-slate-600">
              {t("lineItemPicker.manualCurrencyLabel")}
            </label>
            {documentCurrency ? (
              <div className="mt-1 flex h-[38px] items-center rounded-lg border border-dashed border-slate-200 bg-slate-50 px-3 text-sm text-slate-700">
                {getCurrencyLabel(t, documentCurrency)}
              </div>
            ) : (
              <select
                value={currencyCode}
                onChange={(e) => setCurrencyCode(e.target.value as CurrencyCode)}
                className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm outline-none ring-slate-400 focus:ring-2"
              >
                {CURRENCY_CODES.map((code) => (
                  <option key={code} value={code}>
                    {getCurrencyLabel(t, code)}
                  </option>
                ))}
              </select>
            )}
          </div>

          <div>
            <label className="text-xs font-medium text-slate-600">
              {t("lineItemPicker.descriptionLabel")}
            </label>
            <input
              ref={descriptionRef}
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={t("lineItemPicker.descriptionPlaceholder")}
              className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none ring-slate-400 focus:ring-2"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-medium text-slate-600">
                {t("lineItemPicker.qtyLabel")}
              </label>
              <input
                type="number"
                inputMode="decimal"
                min="0"
                step="0.0001"
                value={quantity}
                onChange={(e) => setQuantity(e.target.value)}
                className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none ring-slate-400 focus:ring-2"
              />
            </div>
            <div>
              <label className="text-xs font-medium text-slate-600">
                {t("lineItemPicker.unitPriceLabel")}
              </label>
              <input
                type="number"
                inputMode="decimal"
                min="0"
                step="0.01"
                value={unitPrice}
                onChange={(e) => setUnitPrice(e.target.value)}
                className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none ring-slate-400 focus:ring-2"
              />
            </div>
          </div>

          {error ? (
            <p className="text-xs text-red-700" role="alert">
              {error}
            </p>
          ) : null}

          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <button
              type="button"
              onClick={onClose}
              className="inline-flex items-center justify-center rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-800 hover:bg-slate-50"
            >
              {t("common.cancel")}
            </button>
            <button
              type="submit"
              className="inline-flex items-center justify-center rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-800"
            >
              {t("lineItemPicker.addLine")}
            </button>
          </div>
        </form>
      </div>
    </div>,
    document.body
  );
}
