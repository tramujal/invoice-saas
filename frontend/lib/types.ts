import type { InvitationRole, MembershipRole, MembershipStatus } from "@/lib/membership-role";
import type { PaymentStatus } from "@/lib/payment-status";
import type { ProductType } from "@/lib/product-type";
import type { QuoteStatus } from "@/lib/quote-status";

export type InvoiceSummary = {
  id: string;
  invoice_number: string;
  customer_id: string | null;
  customer_name: string | null;
  customer_phone: string | null;
  subtotal: string;
  tax_amount: string;
  total: string;
  /** The raw, editable Pending/Paid toggle — see effective_payment_status
   * for what to actually display. */
  payment_status: PaymentStatus;
  /** Derived, read-only (due-date-aware) — the single source of truth to
   * display everywhere (badge, list, dashboard). Never computed client-side. */
  effective_payment_status: PaymentStatus;
  /** Permanently pinned at creation — never re-derived from the
   * organization's current currency. */
  currency_code: string;
  /** Permanently pinned at creation — never re-derived from the
   * organization's current language. */
  language: string;
  due_date: string | null;
  created_at: string;
};

export type PaginatedInvoices = {
  total: number;
  items: InvoiceSummary[];
};

/** Response from POST /organizations/{org}/invoices/{id}/send-email */
export type SendInvoiceEmailResponse = {
  sent: boolean;
  sent_to: string;
};

export type Customer = {
  id: string;
  organization_id: string;
  name: string;
  email: string;
  phone: string;
  address: string;
  tax_id: string;
  created_at: string;
  updated_at: string;
};

export type ImportTargetField = "name" | "email" | "phone" | "address" | "tax_id" | "ignore";

export type ImportPreviewRowStatus = "valid" | "warning" | "invalid" | "duplicate";
export type ImportConfirmRowStatus = "imported" | "skipped" | "failed";

export type ImportPreviewRowResult = {
  row_number: number;
  status: ImportPreviewRowStatus;
  reason_code: string | null;
  values: Record<string, string | null>;
};

export type ImportPreviewResponse = {
  file_type: "csv" | "xlsx";
  headers: string[];
  normalized_headers: string[];
  auto_mapping: Record<string, string>;
  requires_manual_mapping: boolean;
  missing_required_fields: string[];
  total_rows: number;
  preview_rows: ImportPreviewRowResult[];
  valid_count: number;
  warning_count: number;
  invalid_count: number;
  duplicate_count: number;
};

export type ImportConfirmRowResult = {
  row_number: number;
  status: ImportConfirmRowStatus;
  reason_code: string | null;
  values: Record<string, string | null>;
};

export type ImportConfirmResponse = {
  imported_count: number;
  skipped_duplicate_count: number;
  failed_count: number;
  total_processed: number;
  row_results: ImportConfirmRowResult[];
};

export type InvoiceLineItemResponse = {
  id: string;
  description: string;
  quantity: string;
  unit_price: string;
  line_total: string;
  /** Purely an analytics tag ("this line came from this catalog item") --
   * never used to re-derive description/unit_price/line_total, which are
   * always this line's own permanent snapshot. */
  product_id: string | null;
};

/** Response from POST /organizations/{org}/invoices */
export type InvoiceCreatedResponse = {
  id: string;
  invoice_number: string;
  organization_id: string;
  created_by_user_id: string | null;
  customer_id: string | null;
  customer_name: string | null;
  subtotal: string;
  tax_amount: string;
  total: string;
  payment_status: PaymentStatus;
  effective_payment_status: PaymentStatus;
  currency_code: string;
  language: string;
  due_date: string | null;
  line_items: InvoiceLineItemResponse[];
};

/** Response from POST /organizations/{org}/invoices/{id}/send-reminder */
export type SendInvoiceReminderResponse = {
  sent: boolean;
  sent_to: string;
  reminder_type: "before_due" | "due_today" | "after_due" | "manual";
};

export type AuthUser = {
  id: string;
  email: string;
  email_verified: boolean;
};

export type OrganizationSummary = {
  id: string;
  name: string;
  currency_code: string;
  language: string;
  /** The caller's own effective permission set in this organization -- see
   * lib/permissions.ts's Permission union and hasPermission(). */
  permissions: string[];
};

/** Response from POST /auth/login and POST /auth/register */
export type AuthResponse = {
  access_token: string;
  token_type: string;
  user: AuthUser;
  organizations: OrganizationSummary[];
};

/** Response from GET /auth/me */
export type MeResponse = {
  user: AuthUser;
  organizations: OrganizationSummary[];
};

/** Response from POST /auth/resend-verification and POST /auth/verify-email */
export type MessageResponse = {
  message: string;
};

/** Response from GET/PATCH /organizations/{org} */
export type OrganizationProfile = {
  id: string;
  name: string;
  business_name: string | null;
  tax_id: string | null;
  address: string | null;
  phone: string | null;
  email: string | null;
  logo_url: string | null;
  language: string;
  currency_code: string;
  tax_label: string;
  timezone: string;
  reminders_enabled: boolean;
  reminder_before_due_days: number[];
  reminder_on_due_date: boolean;
  reminder_after_due_days: number[];
  /** Independent of the invoice reminder fields above -- see
   * Organization.quote_reminders_enabled's docstring in app/models.py. */
  quote_reminders_enabled: boolean;
  quote_reminder_before_expiry_days: number[];
};

/** Revenue figures for one currency — never combine across currencies
 * (e.g. summing a USD total with a UYU total). One entry per currency
 * present among the organization's invoices. */
export type CurrencyRevenueSummary = {
  currency_code: string;
  total_revenue: string;
  revenue_this_month: string;
  revenue_last_month: string;
  revenue_growth_percent: string | null;
};

/** Response from GET /organizations/{org}/dashboard */
export type DashboardData = {
  total_invoices: number;
  total_customers: number;
  pending_invoices: number;
  paid_invoices: number;
  overdue_invoices: number;
  revenue_by_currency: CurrencyRevenueSummary[];
  recent_invoices: InvoiceSummary[];
};

/** Invoice volume per month — currency-agnostic (a count, not money). */
export type MonthlySummaryPoint = {
  month: string;
  invoice_count: number;
};

/** Revenue per month, per currency. Never aggregate across
 * currency_code values. */
export type MonthlyRevenuePoint = {
  month: string;
  currency_code: string;
  revenue: string;
};

export type PaymentStatusCountPoint = {
  status: PaymentStatus;
  count: number;
};

/** Top customers are ranked independently within each currency — a
 * customer can be "top" in USD and unranked in UYU. */
export type TopCustomerRevenue = {
  customer_id: string;
  customer_name: string;
  currency_code: string;
  revenue: string;
};

/** Same independent-per-currency ranking, for catalog items -- ranked
 * independently per (currency_code, product_type) pair, so "top products"
 * and "top services" never crowd each other out. Filter this one flat
 * list by product_type client-side, the same way top_customers is
 * already filtered by currency. */
export type TopProductRevenue = {
  product_id: string;
  product_name: string;
  product_type: ProductType;
  currency_code: string;
  revenue: string;
  invoice_count: number;
};

export type QuoteStatusCountPoint = {
  status: QuoteStatus;
  count: number;
};

/** Quote pipeline figures for one currency, never combined with any other. */
export type QuoteCurrencyPipelineSummary = {
  currency_code: string;
  revenue_in_quotes: string;
  projected_revenue: string;
  accepted_this_month: number;
  rejected_this_month: number;
  converted_this_month: number;
};

export type QuotePipelineSummary = {
  counts_by_status: QuoteStatusCountPoint[];
  acceptance_rate_percent: number | null;
  by_currency: QuoteCurrencyPipelineSummary[];
};

export type QuoteMonthlyConversionPoint = {
  month: string;
  converted_count: number;
};

/** Response from GET /organizations/{org}/dashboard/analytics */
export type DashboardAnalytics = {
  monthly_summary: MonthlySummaryPoint[];
  monthly_revenue_by_currency: MonthlyRevenuePoint[];
  invoice_count_by_status: PaymentStatusCountPoint[];
  top_customers: TopCustomerRevenue[];
  top_products_and_services: TopProductRevenue[];
  quote_pipeline: QuotePipelineSummary;
  quote_monthly_conversions: QuoteMonthlyConversionPoint[];
  team: TeamSummary;
};

/** Response from GET/POST/PATCH .../products, .../products/{id}/archive,
 * .../products/{id}/restore */
export type Product = {
  id: string;
  organization_id: string;
  name: string;
  description: string;
  type: ProductType;
  sku: string;
  default_unit_price: string;
  currency_code: string;
  default_tax_rate: string;
  active: boolean;
  created_at: string;
  updated_at: string;
};

export type PaginatedProducts = {
  total: number;
  items: Product[];
};

// --- Quotes ----------------------------------------------------------------

export type QuoteLineItem = {
  id: string;
  description: string;
  quantity: string;
  unit_price: string;
  line_total: string;
  product_id: string | null;
};

export type QuoteLineItemInput = {
  description: string;
  quantity: string;
  unit_price: string;
  product_id: string | null;
};

/** Response from GET/POST/PATCH .../quotes/{id} -- the full quote,
 * including line items. */
export type Quote = {
  id: string;
  quote_number: string;
  organization_id: string;
  created_by_user_id: string | null;
  customer_id: string | null;
  customer_name: string | null;
  subtotal: string;
  tax_rate: string;
  tax_amount: string;
  total: string;
  /** The raw, stored status -- see effective_status for what to display. */
  status: QuoteStatus;
  /** Derived, read-only (expiry-date-aware) -- the single source of truth
   * to display everywhere. Never computed client-side. */
  effective_status: QuoteStatus;
  currency_code: string;
  language: string;
  issue_date: string;
  expiry_date: string | null;
  notes: string;
  active: boolean;
  converted_invoice_id: string | null;
  /** The durable, shareable public accept/reject link for this quote. */
  public_url: string;
  created_at: string;
  updated_at: string;
  line_items: QuoteLineItem[];
};

/** Row shape from GET .../quotes (list) -- no line items, matching
 * InvoiceSummary's own narrower list-row shape. */
export type QuoteSummary = {
  id: string;
  quote_number: string;
  customer_id: string | null;
  customer_name: string | null;
  customer_phone: string | null;
  subtotal: string;
  tax_amount: string;
  total: string;
  status: QuoteStatus;
  effective_status: QuoteStatus;
  currency_code: string;
  language: string;
  issue_date: string;
  expiry_date: string | null;
  active: boolean;
  converted_invoice_id: string | null;
  /** The durable, shareable public accept/reject link for this quote. */
  public_url: string;
  created_at: string;
};

export type PaginatedQuotes = {
  total: number;
  items: QuoteSummary[];
};

export type SendQuoteEmailResponse = {
  sent: boolean;
  sent_to: string;
};

export type ConvertQuoteToInvoiceResponse = {
  invoice_id: string;
  invoice_number: string;
};

/** Narrower shape shown on the anonymous public quote page -- no
 * organization_id, created_by_user_id, converted_invoice_id, or
 * product_id anywhere (see app/schemas.py PublicQuoteResponse). */
export type PublicQuoteLineItem = {
  description: string;
  quantity: string;
  unit_price: string;
  line_total: string;
};

export type PublicQuote = {
  quote_number: string;
  organization_name: string;
  customer_name: string | null;
  subtotal: string;
  tax_rate: string;
  tax_amount: string;
  total: string;
  effective_status: QuoteStatus;
  currency_code: string;
  language: string;
  issue_date: string;
  expiry_date: string | null;
  notes: string;
  line_items: PublicQuoteLineItem[];
};

export type PublicQuoteActionResponse = {
  status: QuoteStatus;
};

// --- Dashboard business insights -----------------------------------------
//
// title/message/suggestion arrive already localized from the backend (see
// app/localization.py) -- the frontend never translates insight content
// itself, only the surrounding chrome (section heading, buttons, etc).

export type InsightSeverity = "info" | "warning" | "critical" | "positive";
export type InsightTier = "primary" | "secondary";

export type InsightCtaType =
  | "view_overdue_invoices"
  | "view_due_soon_invoices"
  | "review_pending_invoices"
  | "create_invoice"
  | "ask_assistant"
  | "view_products"
  | "view_pending_quotes"
  | "view_expiring_quotes"
  | "view_team";

export type InsightMetric = {
  currency_code: string | null;
  value: string | null;
  percentage: number | null;
};

export type InsightRelatedEntity = {
  type: "invoice" | "customer" | null;
  id: string | null;
  label: string | null;
};

export type InsightCta = {
  type: InsightCtaType;
  /** Only set for type === "ask_assistant" -- a deterministic, already-
   * localized prefill question, never AI-generated. */
  question: string | null;
};

export type Insight = {
  id: string;
  category: string;
  severity: InsightSeverity;
  tier: InsightTier;
  title: string;
  message: string;
  suggestion: string | null;
  metric: InsightMetric | null;
  related_entity: InsightRelatedEntity | null;
  cta: InsightCta | null;
};

/** Response from GET /organizations/{org}/dashboard/insights */
export type DashboardInsightsResponse = {
  generated_at: string;
  source: "deterministic" | "ai_enhanced";
  ai_available: boolean;
  insights: Insight[];
};

// --- AI assistant actions ----------------------------------------------
//
// The stable set of action names the backend currently registers (see
// app/ai/tools/registry.py). Kept as a union rather than a bare `string`
// so the proposal card can render a bespoke layout per known action while
// still falling back generically for any future action name -- adding a
// new backend tool never requires widening this union for the app to
// keep working, only to get a bespoke layout.
export type AssistantActionName =
  | "create_invoice_draft"
  | "update_invoice_status"
  | "send_invoice_email"
  | "send_payment_reminder"
  | "create_quote_draft"
  | "convert_quote_to_invoice"
  | "send_quote";

/** One NDJSON line from POST /organizations/{org}/assistant/chat. Plain
 * prose streams as a sequence of text_delta events; a proposed action
 * (never executed until the user confirms) streams as one action_proposal
 * event; an ambiguous reference (e.g. two customers matching a name)
 * streams as clarification_needed instead of guessing. */
export type AssistantStreamEvent =
  | { type: "text_delta"; text: string }
  | {
      type: "action_proposal";
      proposal_id: string;
      action: AssistantActionName | string;
      summary: Record<string, unknown>;
      expires_at: string;
    }
  | { type: "clarification_needed"; code: string; candidates: string[] }
  | { type: "error"; code: string };

/** Response from POST .../assistant/actions/{id}/confirm */
export type AssistantActionConfirmResponse = {
  status: "executed";
  action: AssistantActionName | string;
  summary: Record<string, unknown>;
};

/** Response from POST .../assistant/actions/{id}/cancel */
export type AssistantActionCancelResponse = {
  status: "cancelled";
};

/** Local, per-message shape the assistant page renders — a superset of
 * the raw wire events above, since a proposal/clarification message also
 * needs to track its own confirm/cancel UI state over time. */
export type AssistantChatMessage =
  | { kind: "text"; role: "user" | "assistant"; content: string }
  | {
      kind: "proposal";
      proposalId: string;
      action: AssistantActionName | string;
      summary: Record<string, unknown>;
      expiresAt: string;
      status: "pending" | "executing" | "executed" | "cancelling" | "cancelled" | "error";
      resultSummary?: Record<string, unknown>;
    }
  | { kind: "clarification"; code: string; candidates: string[] };

// --- Team & Invitations --------------------------------------------------

/** Response row from GET/PATCH/POST .../members -- see
 * app.schemas.MemberResponse. email is the sole user-facing identifier
 * (the app has no display-name field anywhere). */
export type Member = {
  id: string;
  organization_id: string;
  user_id: string;
  user_email: string;
  role: MembershipRole;
  status: MembershipStatus;
  invited_by_email: string | null;
  invited_at: string | null;
  accepted_at: string;
  created_at: string;
  updated_at: string;
  /** Derived server-side from role via app.permissions.ROLE_PERMISSIONS --
   * gate UI on this, never on `role` directly (see lib/permissions.ts). */
  permissions: string[];
};

export type PaginatedMembers = {
  total: number;
  items: Member[];
};

/** Response row from GET/POST/POST-resend .../invitations -- see
 * app.schemas.InvitationResponse. Always role !== "owner" -- ownership can
 * only be granted through the dedicated grant-ownership action. */
export type Invitation = {
  id: string;
  organization_id: string;
  email: string;
  role: InvitationRole;
  expires_at: string;
  accepted_at: string | null;
  created_by_email: string | null;
  created_at: string;
};

export type PaginatedInvitations = {
  total: number;
  items: Invitation[];
};

/** Response from GET /invitations/public/{token} -- deliberately narrower
 * than Invitation: no ids, nothing beyond what an anonymous visitor needs
 * to decide whether to accept. */
export type PublicInvitation = {
  organization_name: string;
  inviter_email: string | null;
  role: InvitationRole;
  expires_at: string;
  already_accepted: boolean;
  expired: boolean;
};

/** Response from POST /invitations/public/{token}/accept */
export type PublicInvitationAcceptResponse = {
  organization_id: string;
  organization_name: string;
  role: InvitationRole;
};

export type TeamRoleCount = {
  role: MembershipRole;
  count: number;
};

/** Also embedded as DashboardAnalytics.team -- one shared shape, computed
 * by app.team_analytics, reused by both the dashboard and this feature's
 * own team page. */
export type TeamSummary = {
  total_members: number;
  by_role: TeamRoleCount[];
  owner_count: number;
  pending_invitations: number;
};
