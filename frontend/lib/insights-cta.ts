import type { InsightCta } from "@/lib/types";

/** Maps a dashboard insight's CTA to where it navigates. No "open customer"
 * deep link exists -- there is no /customers/{id} route anywhere in this
 * app; customer-specific insights use "ask_assistant" instead. Button
 * labels themselves come from the frontend's own translation keys, keyed
 * off `cta.type` (see the assistant.insights.cta.* keys) -- never from the
 * backend, which only ever supplies the `question` text for ask_assistant. */
export function insightCtaHref(cta: InsightCta): string {
  switch (cta.type) {
    case "view_overdue_invoices":
      return "/invoices?status=overdue";
    case "review_pending_invoices":
      return "/invoices?status=pending";
    case "create_invoice":
      return "/invoices/new";
    case "ask_assistant":
      return `/assistant?q=${encodeURIComponent(cta.question ?? "")}`;
    default:
      return "/dashboard";
  }
}
