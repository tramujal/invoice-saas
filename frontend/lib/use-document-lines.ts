import { useMemo, useState } from "react";

import { parseQuantity, parseUnitPrice, roundMoney } from "@/lib/money";
import type { CurrencyCode } from "@/lib/organization-settings";
import type { Product } from "@/lib/types";

/** A line item being edited on an Invoice or Quote form.
 *
 * `currency_code` and `default_tax_rate` are client-only -- never sent to
 * the backend as per-line fields (the request payload only ever carries
 * description/quantity/unit_price/product_id per line, unchanged from
 * before). They're captured once, at the moment a line is added (from the
 * selected product, or the user's manual-line currency choice), rather
 * than looked up live from a products cache -- this app no longer eagerly
 * preloads the full product catalog, so a line added in one render might
 * reference a product that's no longer in whatever page of search results
 * is currently in memory. Storing the values directly on the line avoids
 * that whole class of stale-lookup bug, including when seeding lines from
 * an existing invoice/quote being edited. */
export type LineDraft = {
  id: string;
  description: string;
  quantity: string;
  unit_price: string;
  product_id: string | null;
  currency_code: CurrencyCode;
  default_tax_rate: string | null;
};

function newLineId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `line-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

type ManualLineInput = {
  currencyCode: CurrencyCode;
  description: string;
  quantity: string;
  unitPrice: string;
};

type UseDocumentLinesOptions = {
  initialLines?: LineDraft[];
  initialTaxPercent?: string;
  taxManuallySetInitially?: boolean;
};

export function useDocumentLines(options: UseDocumentLinesOptions = {}) {
  const [lines, setLines] = useState<LineDraft[]>(options.initialLines ?? []);
  const [taxPercent, setTaxPercentState] = useState<string>(options.initialTaxPercent ?? "0");
  const [taxManuallySet, setTaxManuallySet] = useState(options.taxManuallySetInitially ?? false);

  // The document has no currency until its first line (product or manual)
  // establishes one; clearing every line returns it to that undefined
  // state with no special-case reset code needed. Single-currency
  // compatibility is enforced at add-time (ProductPicker disables
  // incompatible products; ManualLineEditor locks to this value once set),
  // so simply reading the first line's own currency is sufficient here.
  const documentCurrency = useMemo<CurrencyCode | null>(
    () => lines[0]?.currency_code ?? null,
    [lines]
  );

  // Prefills the document's single tax-rate field from a product's
  // default_tax_rate, but only while every product line added so far
  // shares one rate and the user hasn't touched tax manually -- the
  // moment either stops being true, this does nothing further, leaving
  // tax as a normal editable field.
  function maybePrefillTax(candidateLines: LineDraft[]) {
    if (taxManuallySet) return;
    const rates = new Set(
      candidateLines
        .map((l) => l.default_tax_rate)
        .filter((r): r is string => r !== null)
    );
    if (rates.size === 1) {
      const rate = Number(Array.from(rates)[0]);
      if (Number.isFinite(rate)) setTaxPercentState(String(rate * 100));
    }
  }

  function addProductLine(product: Product) {
    setLines((prev) => {
      const next = [
        ...prev,
        {
          id: newLineId(),
          description: product.name,
          quantity: "1",
          unit_price: product.default_unit_price,
          product_id: product.id,
          currency_code: product.currency_code as CurrencyCode,
          default_tax_rate: product.default_tax_rate,
        },
      ];
      maybePrefillTax(next);
      return next;
    });
  }

  function addManualLine({ currencyCode, description, quantity, unitPrice }: ManualLineInput) {
    setLines((prev) => [
      ...prev,
      {
        id: newLineId(),
        description,
        quantity,
        unit_price: unitPrice,
        product_id: null,
        currency_code: currencyCode,
        default_tax_rate: null,
      },
    ]);
  }

  function updateLine(
    id: string,
    patch: Partial<Pick<LineDraft, "description" | "quantity" | "unit_price">>
  ) {
    setLines((prev) => prev.map((row) => (row.id === id ? { ...row, ...patch } : row)));
  }

  function removeLine(id: string) {
    setLines((prev) => prev.filter((row) => row.id !== id));
  }

  function onTaxPercentChange(value: string) {
    setTaxPercentState(value);
    setTaxManuallySet(true);
  }

  const taxRateFraction = useMemo(() => {
    const p = Number(taxPercent);
    if (!Number.isFinite(p) || p < 0) return 0;
    return Math.min(p, 100) / 100;
  }, [taxPercent]);

  const { lineAmounts, subtotal, taxAmount, total } = useMemo(() => {
    const amounts = lines.map((line) => {
      const qty = parseQuantity(line.quantity);
      const price = parseUnitPrice(line.unit_price);
      if (qty === null || price === null) return null;
      return roundMoney(qty * price);
    });

    const sub =
      amounts.length > 0 && amounts.every((v) => v !== null)
        ? roundMoney((amounts as number[]).reduce((acc, v) => roundMoney(acc + v), 0))
        : null;

    const tax = sub !== null ? roundMoney(sub * taxRateFraction) : null;
    const tot = sub !== null && tax !== null ? roundMoney(sub + tax) : null;

    return { lineAmounts: amounts, subtotal: sub, taxAmount: tax, total: tot };
  }, [lines, taxRateFraction]);

  return {
    lines,
    documentCurrency,
    addProductLine,
    addManualLine,
    updateLine,
    removeLine,
    taxPercent,
    onTaxPercentChange,
    taxRateFraction,
    lineAmounts,
    subtotal,
    taxAmount,
    total,
  };
}
