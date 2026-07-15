import { describe, expect, it } from "vitest";

import { translate } from "./i18n/translations";
import { formatCurrency } from "./money";
import { buildInvoiceWhatsappMessage, buildQuoteWhatsappMessage, buildWhatsappUrl } from "./whatsapp";

const t = (key: string, params?: Record<string, string | number>) => translate("en", key, params);

describe("buildInvoiceWhatsappMessage", () => {
  it("includes customer name, invoice number, and formatted currency + amount", () => {
    const message = buildInvoiceWhatsappMessage({
      t,
      customerName: "Acme Corp",
      invoiceNumber: "INV-000005",
      total: "1234.5",
      currencyCode: "USD",
    });

    expect(message).toContain("Acme Corp");
    expect(message).toContain("INV-000005");
    // Goes through the same formatCurrency() the rest of the app uses --
    // asserted via that helper, not a hardcoded separator style, since
    // Number.toLocaleString's punctuation depends on the runtime locale.
    expect(message).toContain(formatCurrency("1234.5", "USD"));
  });

  it("never mentions a link (invoices have no secure public URL today)", () => {
    const message = buildInvoiceWhatsappMessage({
      t,
      customerName: "Acme Corp",
      invoiceNumber: "INV-000005",
      total: "50",
      currencyCode: "USD",
    });

    expect(message).not.toMatch(/https?:\/\//);
  });
});

describe("buildQuoteWhatsappMessage", () => {
  it("includes customer name, quote number, formatted amount, and the public link", () => {
    const message = buildQuoteWhatsappMessage({
      t,
      customerName: "Beta Industries",
      quoteNumber: "Q-000002",
      total: "999",
      currencyCode: "USD",
      publicUrl: "http://localhost:3000/quotes/public/abc123",
    });

    expect(message).toContain("Beta Industries");
    expect(message).toContain("Q-000002");
    expect(message).toContain(formatCurrency("999", "USD"));
    expect(message).toContain("http://localhost:3000/quotes/public/abc123");
  });
});

describe("buildWhatsappUrl", () => {
  it("builds a wa.me URL with the digits-only phone and an encoded message", () => {
    const url = buildWhatsappUrl("15551234567", "Hola & bienvenido\n¿Cómo estás?");

    expect(url.startsWith("https://wa.me/15551234567?text=")).toBe(true);
    expect(url).toContain(encodeURIComponent("Hola & bienvenido\n¿Cómo estás?"));
    // encodeURIComponent must have actually run -- raw special characters
    // should never appear unescaped in the query string.
    expect(url).not.toContain("¿Cómo estás?");
  });
});
