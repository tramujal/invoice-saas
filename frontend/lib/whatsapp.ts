/** Builds a wa.me deep link with a prefilled message -- the app never sends
 * anything itself; this only opens the user's own WhatsApp (Web or app)
 * with the message text already typed in, for the user to review and send
 * manually. See lib/phone.ts for the digits-only normalization wa.me
 * requires. */

import { formatCurrency } from "@/lib/money";

type Translate = (key: string, params?: Record<string, string | number>) => string;

export function buildInvoiceWhatsappMessage(params: {
  t: Translate;
  customerName: string;
  invoiceNumber: string;
  total: string | number;
  currencyCode: string;
}): string {
  return params.t("whatsapp.invoiceMessage", {
    customer: params.customerName,
    number: params.invoiceNumber,
    amount: formatCurrency(params.total, params.currencyCode),
  });
}

export function buildQuoteWhatsappMessage(params: {
  t: Translate;
  customerName: string;
  quoteNumber: string;
  total: string | number;
  currencyCode: string;
  publicUrl: string;
}): string {
  return params.t("whatsapp.quoteMessage", {
    customer: params.customerName,
    number: params.quoteNumber,
    amount: formatCurrency(params.total, params.currencyCode),
    link: params.publicUrl,
  });
}

export function buildWhatsappUrl(normalizedPhone: string, message: string): string {
  return `https://wa.me/${normalizedPhone}?text=${encodeURIComponent(message)}`;
}
