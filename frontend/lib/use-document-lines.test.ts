import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Product } from "@/lib/types";
import { useDocumentLines } from "@/lib/use-document-lines";

function makeProduct(overrides: Partial<Product>): Product {
  return {
    id: "product-1",
    organization_id: "org-1",
    name: "Hosting",
    description: "",
    type: "service",
    sku: "",
    default_unit_price: "15.00",
    currency_code: "USD",
    default_tax_rate: "0",
    active: true,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ...overrides,
  } as Product;
}

describe("useDocumentLines", () => {
  it("has no currency for an empty document", () => {
    const { result } = renderHook(() => useDocumentLines());
    expect(result.current.lines).toHaveLength(0);
    expect(result.current.documentCurrency).toBeNull();
  });

  it("first product line determines the document currency", () => {
    const { result } = renderHook(() => useDocumentLines());
    act(() => result.current.addProductLine(makeProduct({ currency_code: "EUR" })));
    expect(result.current.documentCurrency).toBe("EUR");
  });

  it("manual line sets currency when none is set yet", () => {
    const { result } = renderHook(() => useDocumentLines());
    act(() =>
      result.current.addManualLine({
        currencyCode: "UYU",
        description: "One-off",
        quantity: "1",
        unitPrice: "50",
      })
    );
    expect(result.current.documentCurrency).toBe("UYU");
  });

  it("removing the first line re-derives currency from the new first line", () => {
    const { result } = renderHook(() => useDocumentLines());
    act(() => result.current.addProductLine(makeProduct({ currency_code: "USD" })));
    act(() =>
      result.current.addManualLine({
        currencyCode: "USD",
        description: "Second",
        quantity: "1",
        unitPrice: "10",
      })
    );
    const firstLineId = result.current.lines[0].id;
    expect(result.current.documentCurrency).toBe("USD");

    act(() => result.current.removeLine(firstLineId));
    expect(result.current.lines).toHaveLength(1);
    expect(result.current.documentCurrency).toBe("USD");
  });

  it("clearing to zero lines then adding a different-currency line has no stale state", () => {
    const { result } = renderHook(() => useDocumentLines());
    act(() => result.current.addProductLine(makeProduct({ currency_code: "USD" })));
    const onlyLineId = result.current.lines[0].id;

    act(() => result.current.removeLine(onlyLineId));
    expect(result.current.lines).toHaveLength(0);
    expect(result.current.documentCurrency).toBeNull();

    act(() => result.current.addProductLine(makeProduct({ currency_code: "EUR", id: "product-2" })));
    expect(result.current.documentCurrency).toBe("EUR");
  });

  it("computes subtotal/tax/total from valid lines", () => {
    const { result } = renderHook(() => useDocumentLines());
    act(() =>
      result.current.addManualLine({
        currencyCode: "USD",
        description: "Item",
        quantity: "2",
        unitPrice: "10.00",
      })
    );
    act(() => result.current.onTaxPercentChange("10"));

    expect(result.current.subtotal).toBe(20);
    expect(result.current.taxAmount).toBe(2);
    expect(result.current.total).toBe(22);
  });

  it("prefills tax from a single product's default_tax_rate until manually overridden", () => {
    const { result } = renderHook(() => useDocumentLines());
    act(() =>
      result.current.addProductLine(makeProduct({ currency_code: "USD", default_tax_rate: "0.2" }))
    );
    expect(result.current.taxPercent).toBe("20");

    act(() => result.current.onTaxPercentChange("5"));
    act(() =>
      result.current.addProductLine(
        makeProduct({ id: "product-3", currency_code: "USD", default_tax_rate: "0.2" })
      )
    );
    // Manual override sticks -- a later product line's default_tax_rate no
    // longer overwrites it.
    expect(result.current.taxPercent).toBe("5");
  });
});
