"use client";

import { useRef, useState } from "react";

import { useTranslation } from "@/lib/i18n/useTranslation";
import { formatMoney } from "@/lib/money";
import { getCurrencyLabel, type CurrencyCode } from "@/lib/organization-settings";
import type { Product } from "@/lib/types";
import type { LineDraft } from "@/lib/use-document-lines";

import { ManualLineEditor } from "./ManualLineEditor";
import { ProductPicker } from "./ProductPicker";

type LineItemsEditorProps = {
  lines: LineDraft[];
  documentCurrency: CurrencyCode | null;
  defaultCurrency: CurrencyCode;
  lineAmounts: (number | null)[];
  onAddProductLine: (product: Product) => void;
  onAddManualLine: (data: {
    currencyCode: CurrencyCode;
    description: string;
    quantity: string;
    unitPrice: string;
  }) => void;
  onUpdateLine: (id: string, patch: Partial<Pick<LineDraft, "description" | "quantity" | "unit_price">>) => void;
  onRemoveLine: (id: string) => void;
  disabled?: boolean;
};

export function LineItemsEditor({
  lines,
  documentCurrency,
  defaultCurrency,
  lineAmounts,
  onAddProductLine,
  onAddManualLine,
  onUpdateLine,
  onRemoveLine,
  disabled,
}: LineItemsEditorProps) {
  const { t } = useTranslation();
  const addLineButtonRef = useRef<HTMLButtonElement>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [manualEditorOpen, setManualEditorOpen] = useState(false);

  function closePicker() {
    setPickerOpen(false);
    addLineButtonRef.current?.focus();
  }

  function handleSelectProduct(product: Product) {
    onAddProductLine(product);
    closePicker();
  }

  function openManualEditor() {
    setPickerOpen(false);
    setManualEditorOpen(true);
  }

  function closeManualEditor() {
    setManualEditorOpen(false);
    addLineButtonRef.current?.focus();
  }

  function handleManualSubmit(data: {
    currencyCode: CurrencyCode;
    description: string;
    quantity: string;
    unitPrice: string;
  }) {
    onAddManualLine(data);
    closeManualEditor();
  }

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-6">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
            {t("lineItemPicker.lineItemsSectionTitle")}
          </h2>
          {documentCurrency ? (
            <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-700">
              {t("lineItemPicker.currencyBadgeLabel", {
                currency: getCurrencyLabel(t, documentCurrency),
              })}
            </span>
          ) : null}
        </div>
        <button
          ref={addLineButtonRef}
          type="button"
          onClick={() => setPickerOpen(true)}
          disabled={disabled}
          className="inline-flex items-center justify-center rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-medium text-slate-800 hover:bg-slate-100 disabled:cursor-not-allowed"
        >
          {t("lineItemPicker.addLine")}
        </button>
      </div>

      <ProductPicker
        open={pickerOpen}
        anchorRef={addLineButtonRef}
        documentCurrency={documentCurrency}
        onClose={closePicker}
        onSelectProduct={handleSelectProduct}
        onCreateManualLine={openManualEditor}
      />
      <ManualLineEditor
        open={manualEditorOpen}
        documentCurrency={documentCurrency}
        defaultCurrency={defaultCurrency}
        onClose={closeManualEditor}
        onSubmit={handleManualSubmit}
      />

      <div className="mt-4 space-y-4">
        {lines.length === 0 ? (
          <p className="rounded-xl border border-dashed border-slate-200 bg-slate-50/60 px-4 py-6 text-center text-sm text-slate-500">
            {t("lineItemPicker.emptyState")}
          </p>
        ) : (
          lines.map((line, index) => (
            <div key={line.id} className="rounded-xl border border-slate-100 bg-slate-50/60 p-3 sm:p-4">
              <div className="mb-2 flex items-center justify-between gap-2">
                <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                  {t("lineItemPicker.lineLabel", { number: index + 1 })}
                </span>
                <button
                  type="button"
                  onClick={() => onRemoveLine(line.id)}
                  disabled={disabled}
                  className="text-xs font-medium text-red-600 hover:text-red-700 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {t("common.remove")}
                </button>
              </div>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-12 sm:gap-4">
                <div className="sm:col-span-5">
                  <label className="text-xs font-medium text-slate-600">
                    {t("lineItemPicker.descriptionLabel")}
                  </label>
                  <input
                    type="text"
                    value={line.description}
                    onChange={(e) => onUpdateLine(line.id, { description: e.target.value })}
                    disabled={disabled}
                    className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none ring-slate-400 focus:ring-2"
                  />
                  {line.product_id ? (
                    <p className="mt-1 text-xs text-slate-500">
                      {t("lineItemPicker.productLinkedNote")}
                    </p>
                  ) : null}
                </div>
                <div className="grid grid-cols-2 gap-3 sm:col-span-4 sm:grid-cols-2">
                  <div>
                    <label className="text-xs font-medium text-slate-600">
                      {t("lineItemPicker.qtyLabel")}
                    </label>
                    <input
                      type="number"
                      inputMode="decimal"
                      min="0"
                      step="0.0001"
                      value={line.quantity}
                      onChange={(e) => onUpdateLine(line.id, { quantity: e.target.value })}
                      disabled={disabled}
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
                      value={line.unit_price}
                      onChange={(e) => onUpdateLine(line.id, { unit_price: e.target.value })}
                      disabled={disabled}
                      className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none ring-slate-400 focus:ring-2"
                    />
                  </div>
                </div>
                <div className="sm:col-span-3">
                  <label className="text-xs font-medium text-slate-600">
                    {t("lineItemPicker.lineTotalLabel")}
                  </label>
                  <div className="mt-1 flex h-[42px] items-center rounded-lg border border-dashed border-slate-200 bg-white px-3 text-sm font-medium text-slate-900">
                    {lineAmounts[index] === null ? "—" : formatMoney(lineAmounts[index] as number)}
                  </div>
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </section>
  );
}
