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
  /** Phase 28 -- the tax rate for THIS line, held as a percent string
   * ("22", "10", "0") because that's what the user types and what the
   * <select>/<input> pair binds to. Converted to the fraction the API
   * expects (0.22) only at submit time.
   *
   * Seeded from the product's default_tax_rate when a product line is
   * added, and freely editable afterward -- editing it never touches the
   * product (see docs/taxes_and_rut.md). */
  tax_percent: string;
};

/** The tax rates offered as one-click presets. Uruguay's IVA rates plus
 * exempt, because that is what this product's users need most often --
 * but the field itself remains a free numeric input, so nothing here
 * assumes a country or forecloses any other rate. */
export const TAX_RATE_PRESETS = ["22", "10", "0"] as const;

export type TaxGroupSummary = {
  /** Percent string, e.g. "22". */
  percent: string;
  base: number;
  tax: number;
};

/** "0.22" -> "22". Products store the rate as a fraction string; the
 * line editor works in percent. */
export function percentFromFraction(fraction: string | null): string {
  if (fraction === null) return "0";
  const value = Number(fraction);
  if (!Number.isFinite(value)) return "0";
  return String(Number((value * 100).toFixed(4)));
}

/** "22" -> 0.22, for the API payload. Clamped to the 0..1 range the
 * backend schema enforces, so a typo can't produce a rejected request
 * the user has no way to interpret. */
export function fractionFromPercent(percent: string): number {
  const value = Number(percent);
  if (!Number.isFinite(value) || value < 0) return 0;
  return Number((Math.min(value, 100) / 100).toFixed(4));
}

/** Canonical grouping key, so "22", "22.0" and " 22 " are one group
 * rather than three rows that all display as 22%. */
function normalizeTaxPercent(percent: string): string {
  const value = Number(percent);
  if (!Number.isFinite(value) || value < 0) return "0";
  return String(Number(Math.min(value, 100).toFixed(4)));
}

/** The rate to start a new manual line at: the document's rate when
 * every existing line agrees, otherwise exempt (guessing on a mixed
 * document would be worse than making the user choose). */
function dominantTaxPercent(lines: LineDraft[]): string {
  const rates = new Set(lines.map((line) => normalizeTaxPercent(line.tax_percent)));
  return rates.size === 1 ? Array.from(rates)[0] : "0";
}

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
          // Prefill only -- a snapshot of the catalog default at the
          // moment this line was added, editable per line from here on.
          tax_percent: percentFromFraction(product.default_tax_rate),
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
        // A manual line has no catalog default to inherit. It follows
        // the rate already in use when the document is unambiguous, so
        // adding "shipping" to an all-22% invoice doesn't silently land
        // at 0%; otherwise it starts exempt and the user picks.
        tax_percent: dominantTaxPercent(lines),
      },
    ]);
  }

  function updateLine(
    id: string,
    patch: Partial<Pick<LineDraft, "description" | "quantity" | "unit_price" | "tax_percent">>
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

  const { lineAmounts, subtotal, taxGroups, taxAmount, total } = useMemo(() => {
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

    if (sub === null) {
      return { lineAmounts: amounts, subtotal: null, taxGroups: [], taxAmount: null, total: null };
    }

    // Grouped by rate and rounded once per group -- deliberately the same
    // rule as the backend's compute_invoice_totals, so the preview the
    // user sees while typing is the number the server will store. Doing
    // it per line here would show a total a cent away from the saved one
    // on some documents.
    const bases = new Map<string, number>();
    lines.forEach((line, index) => {
      const amount = amounts[index];
      if (amount === null) return;
      const key = normalizeTaxPercent(line.tax_percent);
      bases.set(key, roundMoney((bases.get(key) ?? 0) + amount));
    });

    const groups: TaxGroupSummary[] = Array.from(bases.entries())
      .map(([percent, base]) => ({
        percent,
        base,
        tax: roundMoney(base * (Number(percent) / 100)),
      }))
      .sort((a, b) => Number(b.percent) - Number(a.percent));

    const tax = roundMoney(groups.reduce((acc, g) => roundMoney(acc + g.tax), 0));

    return {
      lineAmounts: amounts,
      subtotal: sub,
      taxGroups: groups,
      taxAmount: tax,
      total: roundMoney(sub + tax),
    };
  }, [lines]);

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
    taxGroups,
    taxAmount,
    total,
  };
}
