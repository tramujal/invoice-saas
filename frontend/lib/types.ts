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

// Phase UX5 -- tiered customer duplicate detection. Mirrors
// app.customer_duplicates.DuplicateSeverity exactly.
export type CustomerDuplicateSeverity = "none" | "suggestion" | "warning" | "blocking";

export type CustomerDuplicateMatch = {
  customer_id: string;
  customer_name: string;
  email: string;
  phone: string;
  tax_id: string;
  reasons: string[];
};

export type CustomerDuplicateCheckResponse = {
  severity: CustomerDuplicateSeverity;
  matches: CustomerDuplicateMatch[];
};

// Structured 409 body from POST/PATCH .../customers when a tax_id already
// belongs to another customer (see
// app.services.customers.TaxIdDuplicateError.to_error_detail).
export type TaxIdDuplicateDetail = {
  code: "duplicate_tax_id";
  message: string;
  customer_id: string;
  customer_name: string;
};

export type ImportTargetField = "name" | "email" | "phone" | "address" | "tax_id" | "ignore";

export type ImportPreviewRowStatus = "valid" | "warning" | "invalid" | "duplicate";
export type ImportConfirmRowStatus = "imported" | "skipped" | "failed";

export type ImportPreviewRowResult = {
  row_number: number;
  status: ImportPreviewRowStatus;
  reason_code: string | null;
  values: Record<string, string | null>;
  // Set only for a duplicate row that collided with a real, existing
  // database customer -- null for an in-file-only duplicate (see
  // app.routers.customer_imports._duplicate_customer_match).
  duplicate_customer_id: string | null;
  duplicate_customer_name: string | null;
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
  duplicate_customer_id: string | null;
  duplicate_customer_name: string | null;
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
  /** The caller's own platform-administration role (see
   * app.platform_permissions on the backend), entirely independent from
   * any organization role. Null for every ordinary user. Only ever used
   * client-side to decide whether to show the Platform Admin entry point
   * -- never a source of truth for authorization, which the backend
   * always re-checks live. */
  platform_role: string | null;
};

export type OrganizationSummary = {
  id: string;
  name: string;
  currency_code: string;
  language: string;
  /** The caller's own effective permission set in this organization -- see
   * lib/permissions.ts's Permission union and hasPermission(). */
  permissions: string[];
  /** Set by a platform admin via the admin console (see
   * PlatformOrganizationDetail below) -- checked by AppShell on every
   * /auth/me refresh: if the *active* organization is suspended, AppShell
   * shows a blocking notice instead of its children, since every
   * org-scoped API call would otherwise 403 anyway. */
  status: "active" | "suspended";
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

// --- Phase 16A/16B: Business Analytics KPI snapshot ------------------------
//
// Mirrors app.analytics.time_windows.TimeWindowKind and app.schemas'
// TimeWindowResponse/InvoiceCountsResponse/RevenueBreakdownResponse/
// CustomerRetentionResponse/AveragePaymentTimeResponse/KpiSnapshotResponse
// exactly (see app/routers/analytics.py). Every value here is already
// computed server-side by AnalyticsService -- this page only ever renders
// and formats these fields, never recomputes or re-derives a metric from
// raw invoice/customer/quote data client-side.

/** The 8 window kinds this endpoint accepts -- "custom" is deliberately
 * excluded, since GET /analytics/kpis rejects it with 400
 * custom_window_not_supported (no custom start/end query params exist on
 * this route yet). */
export type AnalyticsTimeWindowKind =
  | "today"
  | "yesterday"
  | "last_7_days"
  | "last_30_days"
  | "current_month"
  | "previous_month"
  | "current_quarter"
  | "current_year";

export const ANALYTICS_TIME_WINDOWS: AnalyticsTimeWindowKind[] = [
  "today",
  "yesterday",
  "last_7_days",
  "last_30_days",
  "current_month",
  "previous_month",
  "current_quarter",
  "current_year",
];

export type AnalyticsTimeWindow = {
  kind: AnalyticsTimeWindowKind;
  start: string;
  end: string;
};

export type AnalyticsInvoiceCounts = {
  total: number;
  pending: number;
  paid: number;
  overdue: number;
};

/** One currency's revenue split by effective payment status -- paid +
 * outstanding always sum back to total. Never combine rows across
 * currency_code values. */
export type AnalyticsRevenueBreakdown = {
  currency_code: string;
  total: string;
  paid: string;
  outstanding: string;
  overdue: string;
};

export type AnalyticsCustomerRetention = {
  total_invoiced_customers: number;
  repeat_customers: number;
  /** null when there is no lifetime invoiced-customer history yet --
   * render as "not enough data", never coerce to 0%. */
  retention_rate_percent: number | null;
};

/** available=false is an honest, documented gap (no invoice has a paid_at
 * timestamp yet), not an error -- render `reason`, never "0 days". */
export type AnalyticsAveragePaymentTime = {
  available: boolean;
  average_days: number | null;
  reason: string | null;
};

/** Response from GET /organizations/{org}/analytics/kpis */
export type KpiSnapshot = {
  window: AnalyticsTimeWindow;
  invoice_counts: AnalyticsInvoiceCounts;
  /** Never sum these values across currency keys. */
  revenue_by_currency: Record<string, string>;
  revenue_breakdown: AnalyticsRevenueBreakdown[];
  /** Never sum/average these values across currency keys. */
  average_invoice_value: Record<string, string>;
  customer_growth: number;
  /** Deliberately all-time, not window-scoped -- a lifetime relationship
   * metric, unlike every other field here. */
  customer_retention: AnalyticsCustomerRetention;
  /** null when the organization has no quotes yet -- render as "not
   * enough data", never coerce to 0%. */
  quote_acceptance_rate_percent: number | null;
  average_payment_time: AnalyticsAveragePaymentTime;
};

// --- Phase 16C: trend analysis & forecasting -------------------------------
//
// Mirrors app.analytics.comparison.PeriodComparison / app.analytics.
// calculators.trends.SeriesPoint / app.analytics.forecast.Forecast and
// app/schemas.py's TrendSnapshotResponse (GET .../analytics/trends).
// Every value here is already computed server-side by AnalyticsService's
// trend engine -- this page only ever renders and formats these fields,
// never recomputes a comparison, series point, or forecast client-side.

export type TrendDirection = "up" | "down" | "flat" | "unknown";

/** The 5 comparison kinds GET .../analytics/trends accepts (see
 * app.analytics.time_windows.COMPARISON_KINDS) -- "today"/"yesterday"
 * are too short a span for a meaningful comparison, and "previous_month"/
 * "custom" are window selections, not a comparison request. */
export type ComparisonPeriodKind =
  | "current_month"
  | "current_quarter"
  | "current_year"
  | "last_7_days"
  | "last_30_days";

export const COMPARISON_PERIOD_KINDS: ComparisonPeriodKind[] = [
  "current_month",
  "current_quarter",
  "current_year",
  "last_7_days",
  "last_30_days",
];

export type SeriesGranularity = "monthly" | "quarterly" | "yearly";

/** Never exposes only a percentage (see this phase's own spec) -- every
 * field here is independently meaningful: "$1,200 -> $1,450 (+$250,
 * +20.8%, up)", not just "+20.8%". */
export type PeriodComparison = {
  current: string;
  previous: string;
  absolute_difference: string;
  percentage_difference: string | null;
  direction: TrendDirection;
};

/** One point in a generic evolution series -- `period`'s format depends
 * on the request's granularity ("2026-07" monthly, "2026-Q3" quarterly,
 * "2026" yearly). `currency_code` is null for currency-agnostic series
 * (invoice/customer/quote counts). Deliberately generic, not a chart-
 * specific shape -- the same series feeds a line chart, a bar chart, or
 * a plain table. */
export type SeriesPoint = {
  period: string;
  value: string;
  currency_code: string | null;
};

export type ForecastMethod = "simple_moving_average" | "weighted_moving_average" | "linear_trend";

/** available=false is an honest gap (fewer than 2 historical periods),
 * never a fabricated forecast_value -- same pattern as
 * AnalyticsAveragePaymentTime. `inputs`/`method`/`window_size` are the
 * forecast's own transparency: this page builds its translated
 * explanation from these structured values, never from a raw backend
 * string (there isn't one -- see app.analytics.forecast's own docstring
 * on why `reason` is the only prose field, and only for the unavailable
 * case). */
export type Forecast = {
  available: boolean;
  method: ForecastMethod | null;
  forecast_value: string | null;
  inputs: string[];
  window_size: number | null;
  reason: string | null;
  /** True when the org's plan doesn't include forecasting (see
   * app.billing.enforcement -- Phase 17B soft-gate), distinct from
   * available=false's "not enough history yet". Defaults to false so
   * older cached snapshots without this field still render the
   * not-enough-data copy rather than an upgrade prompt. */
  plan_restricted?: boolean;
};

/** Response from GET /organizations/{org}/analytics/trends */
export type TrendSnapshot = {
  comparison_kind: ComparisonPeriodKind;
  granularity: SeriesGranularity;
  /** Never sum these across currency keys. */
  revenue_trend: Record<string, PeriodComparison>;
  invoice_count_trend: PeriodComparison;
  customer_growth_trend: PeriodComparison;
  quote_count_trend: PeriodComparison;
  revenue_series: SeriesPoint[];
  invoice_count_series: SeriesPoint[];
  customer_count_series: SeriesPoint[];
  quote_conversion_series: SeriesPoint[];
  /** Never sum/compare these across currency keys. */
  revenue_forecast: Record<string, Forecast>;
  invoice_count_forecast: Forecast;
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
  | { type: "error"; code: string }
  | ({ type: "error"; code: "plan_limit_reached" } & Omit<PlanLimitReachedDetail, "code">);

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

// --- Platform administration (app.routers.platform_admin, read-only) ---
//
// `created_at` on both org/user summary and detail types is NOT a real
// persisted timestamp -- it's derived from the earliest active
// membership row (see the backend schema docstrings in app/schemas.py).
// Every page that renders it must label it as approximate/derived, never
// as a bare "Created" field -- see admin.createdApprox in translations.ts.

export type PlatformSystemHealth = {
  database_reachable: boolean;
  email_provider_configured: boolean;
  email_provider: string | null;
  ai_provider_configured: boolean;
  ai_provider: string | null;
  reminder_emails_pending: number;
  reminder_emails_sent_7d: number;
  reminder_emails_failed_7d: number;
  // Phase 21 additions -- see app.platform_metrics.health.
  queue_pending: number;
  queue_running: number;
  queue_retry_scheduled: number;
  jobs_failed_total: number;
  jobs_succeeded_total: number;
  storage_used_mb: number;
  database_size_mb: number | null;
  average_api_latency_ms: number | null;
  error_rate_percent: number | null;
  request_sample_count: number;
};

// Phase 21: Platform Operations Dashboard
export type PlatformBusinessMetrics = {
  organizations_total: number;
  active_users_total: number;
  paying_organizations: number;
  trial_organizations: number;
  mrr: string;
  arr: string;
  currency: string;
  churn_rate_30d: number;
  conversion_rate_30d: number;
  average_revenue_per_organization: string;
};

export type PlatformUsageMetrics = {
  ai_requests_30d: number;
  api_keys_active: number;
  api_keys_used_7d: number;
  webhook_deliveries_30d: number;
  webhook_deliveries_succeeded_30d: number;
  webhook_deliveries_failed_30d: number;
  background_jobs_30d: number;
  background_jobs_succeeded_30d: number;
  background_jobs_failed_30d: number;
  emails_sent_30d: number;
  notifications_created_30d: number;
};

export type PlatformDailySignupCount = { day: string; count: number };
export type PlatformWeeklyActiveOrganizationsCount = { week_start: string; count: number };
export type PlatformFeatureAdoption = {
  feature: string;
  adopted_paying_organizations: number;
  adopted_percent: number;
};

export type PlatformGrowthMetrics = {
  daily_signups: PlatformDailySignupCount[];
  weekly_active_organizations: PlatformWeeklyActiveOrganizationsCount[];
  monthly_growth_percent: number;
  feature_adoption: PlatformFeatureAdoption[];
};

export type PlatformSettings = {
  maintenance_mode: boolean;
  registrations_enabled: boolean;
  ai_enabled: boolean;
  emails_enabled: boolean;
  invoice_reminders_enabled: boolean;
  quote_reminders_enabled: boolean;
  default_language: string;
  default_currency: string;
  updated_at: string;
  updated_by_email: string | null;
  version: number;

  ai_provider: string | null;
  email_provider: string | null;
  cors_allowed_origins: string[];
};

export type PlatformSettingsUpdateRequest = {
  reason: string;
  expected_version: number;
  maintenance_mode?: boolean;
  registrations_enabled?: boolean;
  ai_enabled?: boolean;
  emails_enabled?: boolean;
  invoice_reminders_enabled?: boolean;
  quote_reminders_enabled?: boolean;
  default_language?: string;
  default_currency?: string;
};

/** GET /public/config -- the only two values the unauthenticated login/
 * register UI needs. See app.schemas.PublicConfigResponse's own docstring
 * for why nothing else belongs here. */
export type PublicConfig = {
  maintenance_mode: boolean;
  registrations_enabled: boolean;
};

export type PlatformDashboard = {
  organizations_total: number;
  organizations_new_7d: number;
  organizations_new_30d: number;
  users_total: number;
  users_new_7d: number;
  users_new_30d: number;
  invoices_total: number;
  quotes_total: number;
  customers_total: number;
  products_total: number;
  reminder_emails_sent_7d: number;
  reminder_emails_failed_7d: number;
  ai_actions_executed_7d: number;
  health: PlatformSystemHealth;
};

export type PlatformOrganizationStatus = "active" | "suspended";

export type PlatformOrganizationSummary = {
  id: string;
  name: string;
  business_name: string | null;
  status: PlatformOrganizationStatus;
  owner_email: string | null;
  members_count: number;
  invoices_count: number;
  quotes_count: number;
  customers_count: number;
  created_at: string | null;
  last_activity_at: string | null;
};

export type PlatformOrganizationMember = {
  user_id: string;
  email: string;
  role: string;
  status: string;
  joined_at: string;
};

export type PlatformOrganizationRecentDocument = {
  type: "invoice" | "quote";
  number: string;
  status: string;
  total: string;
  currency_code: string;
  created_at: string;
};

export type PlatformOrganizationDetail = {
  id: string;
  name: string;
  business_name: string | null;
  status: PlatformOrganizationStatus;
  owner_email: string | null;
  members_count: number;
  invoices_count: number;
  quotes_count: number;
  customers_count: number;
  products_count: number;
  language: string;
  currency_code: string;
  timezone: string;
  plan_id: string;
  plan_code: string;
  plan_name: string;
  usage: OrganizationUsage;
  created_at: string | null;
  last_activity_at: string | null;
  members: PlatformOrganizationMember[];
  recent_documents: PlatformOrganizationRecentDocument[];
};

// NULL = unlimited, 0 = unavailable, positive integer = hard limit --
// see app.models.Plan's own docstring. Shared shape between the
// platform-admin plan response and the organization-facing entitlements
// response.
export type PlanLimits = {
  max_users: number | null;
  max_customers: number | null;
  max_products: number | null;
  max_invoices_per_month: number | null;
  max_quotes_per_month: number | null;
  max_ai_actions_per_month: number | null;
  storage_limit_mb: number | null;
  // Phase 17A
  max_api_keys: number | null;
  max_webhooks: number | null;
};

export type PlanFeatures = {
  custom_branding_enabled: boolean;
  api_access_enabled: boolean;
  advanced_reports_enabled: boolean;
  // Phase 17A
  analytics_enabled: boolean;
  forecasting_enabled: boolean;
  ai_enabled: boolean;
  background_jobs_enabled: boolean;
};

export type Plan = {
  id: string;
  // `code` is the plan's immutable internal identifier (never renamed
  // once created -- see app.models.Plan's own docstring); `name` is the
  // editable display name Platform Admin can change freely.
  code: string;
  name: string;
  description: string | null;
  is_active: boolean;
  is_default: boolean;
  sort_order: number;
  // Phase 17A
  public: boolean;
  monthly_price: string | null;
  yearly_price: string | null;
  currency: string;
  limits: PlanLimits;
  features: PlanFeatures;
  version: number;
  created_at: string;
  updated_at: string;
};

export type PlansListResponse = {
  items: Plan[];
};

export type PlanCreateRequest = {
  code: string;
  name: string;
  description?: string | null;
  sort_order?: number;
  public?: boolean;
  monthly_price?: string | null;
  yearly_price?: string | null;
  currency?: string;
  max_users?: number | null;
  max_customers?: number | null;
  max_products?: number | null;
  max_invoices_per_month?: number | null;
  max_quotes_per_month?: number | null;
  max_ai_actions_per_month?: number | null;
  storage_limit_mb?: number | null;
  max_api_keys?: number | null;
  max_webhooks?: number | null;
  custom_branding_enabled?: boolean;
  api_access_enabled?: boolean;
  advanced_reports_enabled?: boolean;
  analytics_enabled?: boolean;
  forecasting_enabled?: boolean;
  ai_enabled?: boolean;
  background_jobs_enabled?: boolean;
  reason: string;
};

export type PlanUpdateRequest = {
  reason: string;
  expected_version: number;
  name?: string;
  description?: string | null;
  sort_order?: number;
  public?: boolean;
  monthly_price?: string | null;
  yearly_price?: string | null;
  currency?: string;
  max_users?: number | null;
  max_customers?: number | null;
  max_products?: number | null;
  max_invoices_per_month?: number | null;
  max_quotes_per_month?: number | null;
  max_ai_actions_per_month?: number | null;
  storage_limit_mb?: number | null;
  max_api_keys?: number | null;
  max_webhooks?: number | null;
  custom_branding_enabled?: boolean;
  api_access_enabled?: boolean;
  advanced_reports_enabled?: boolean;
  analytics_enabled?: boolean;
  forecasting_enabled?: boolean;
  ai_enabled?: boolean;
  background_jobs_enabled?: boolean;
};

export type PlanActionRequest = {
  reason: string;
  expected_version: number;
};

export type OrganizationPlanChangeRequest = {
  plan_id: string;
  reason: string;
};

// GET /organizations/{id}/entitlements -- the tenant-facing, read-only
// view of what an organization's current plan allows.
export type OrganizationEntitlements = {
  plan_id: string;
  plan_code: string;
  plan_name: string;
  limits: PlanLimits;
  features: PlanFeatures;
};

// --- Phase 17A: Billing domain -------------------------------------------

export type SubscriptionStatus =
  | "trialing"
  | "active"
  | "past_due"
  | "paused"
  | "canceled"
  | "expired"
  | "inactive";

export type BillingPeriod = "monthly" | "yearly";

// The resolved capability layer (see app.billing.capabilities) -- feature
// flags plus remaining quotas, so the frontend never has to re-derive
// "can I create another X" from raw limits/usage itself.
export type Capabilities = {
  can_use_ai: boolean;
  can_use_analytics: boolean;
  can_use_forecasting: boolean;
  can_use_background_jobs: boolean;
  can_create_invoice: boolean;
  can_create_quote: boolean;
  can_create_api_key: boolean;
  can_create_webhook: boolean;
  remaining_invoice_quota: number | null;
  remaining_quote_quota: number | null;
  remaining_users: number | null;
  remaining_api_keys: number | null;
  remaining_webhooks: number | null;
};

// GET /organizations/{id}/subscription -- the tenant-facing, read-only
// view of an organization's own subscription. Deliberately excludes
// provider_name/provider_reference: this app has no payment provider
// integrated in this phase, and never will expose provider internals
// through the tenant API even once one exists.
export type Subscription = {
  id: string;
  organization_id: string;
  plan: Plan;
  status: SubscriptionStatus;
  billing_period: BillingPeriod;
  trial_start: string | null;
  trial_end: string | null;
  current_period_start: string;
  current_period_end: string;
  cancel_at_period_end: boolean;
  canceled_at: string | null;
  ended_at: string | null;
  capabilities: Capabilities;
  created_at: string;
  updated_at: string;
};

// --- Phase 19: self-service checkout + billing portal --------------------

// GET /organizations/{id}/billing/plans -- every active, public plan a
// tenant can choose from (see Plan.public's own docstring on why a
// legacy/grandfathered plan is excluded here but not from Plan itself).
export type PublicPlansResponse = Plan[];

export type StartCheckoutRequest = {
  plan_id: string;
  billing_period: BillingPeriod;
  success_url: string;
  cancel_url: string;
};

export type StartCheckoutResponse = {
  checkout_url: string;
};

export type StartPortalSessionRequest = {
  return_url: string;
};

export type StartPortalSessionResponse = {
  portal_url: string;
};

// One row of subscription HISTORY (see app.models.SubscriptionEvent) --
// distinct from the platform Audit Log: this is "what happened to this
// subscription over time," not "who did what."
export type SubscriptionEvent = {
  id: string;
  subscription_id: string;
  organization_id: string;
  actor_user_id: string | null;
  event_type: string;
  previous_values: Record<string, unknown> | null;
  new_values: Record<string, unknown> | null;
  metadata: Record<string, unknown> | null;
  created_at: string;
};

// GET /admin/subscriptions -- one row per organization's subscription,
// deliberately narrower than the detail response (no event history),
// matching PlatformOrganizationSummary's own list-vs-detail precedent.
export type PlatformSubscriptionSummary = {
  id: string;
  organization_id: string;
  organization_name: string;
  plan_code: string;
  plan_name: string;
  status: SubscriptionStatus;
  billing_period: BillingPeriod;
  trial_end: string | null;
  current_period_end: string;
  cancel_at_period_end: boolean;
  created_at: string;
};

export type PaginatedPlatformSubscriptions = {
  total: number;
  items: PlatformSubscriptionSummary[];
};

// GET /admin/subscriptions/{id} -- the full subscription plus its own
// event history, for platform-admin inspection.
export type PlatformSubscriptionDetail = {
  id: string;
  organization_id: string;
  organization_name: string;
  plan: Plan;
  status: SubscriptionStatus;
  billing_period: BillingPeriod;
  trial_start: string | null;
  trial_end: string | null;
  current_period_start: string;
  current_period_end: string;
  cancel_at_period_end: boolean;
  canceled_at: string | null;
  ended_at: string | null;
  created_at: string;
  updated_at: string;
  events: SubscriptionEvent[];
};

export type AdminChangeSubscriptionPlanRequest = {
  plan_id: string;
  reason: string;
};

export type AdminSubscriptionActionRequest = {
  reason: string;
};

// GET /organizations/{id}/usage -- Phase 14B measures usage only; this
// never rejects a request or implies a warning threshold, it is a plain
// read-only snapshot. See app.services.organization_usage.ResourceUsage.
export type UsageResourceSnapshot = {
  used: number;
  limit: number | null;
  unlimited: boolean;
};

export type OrganizationUsage = {
  users: UsageResourceSnapshot;
  customers: UsageResourceSnapshot;
  products: UsageResourceSnapshot;
  invoices: UsageResourceSnapshot;
  quotes: UsageResourceSnapshot;
  ai_actions: UsageResourceSnapshot;
  storage: UsageResourceSnapshot;
};

// Phase 14C -- the structured 409 body every plan-limit-enforced create
// endpoint returns (see app.services.plan_limits.PlanLimitExceededError
// .to_error_detail()). `resource` matches OrganizationUsage's own field
// names (never a Plan column name like "max_users"), and `message` is
// never parsed -- every UI decision is made from the structured fields.
export type PlanLimitReachedResource =
  | "users"
  | "customers"
  | "products"
  | "invoices"
  | "quotes"
  | "ai_actions"
  // Phase 17B
  | "api_keys"
  | "webhooks";

export type PlanLimitReachedDetail = {
  code: "plan_limit_reached";
  resource: PlanLimitReachedResource;
  used: number;
  limit: number;
  plan: { id: string; code: string; name: string };
  message: string;
};

// Phase 17B -- the structured 403 body every all-or-nothing plan-feature
// gate returns (see app.billing.enforcement.CapabilityDeniedError
// .to_error_detail()). Distinct from PlanLimitReachedDetail above: this
// is "your plan doesn't include this feature at all", never a
// used-vs-limit quota.
export type CapabilityDeniedFeature = "ai" | "analytics";

export type CapabilityDeniedDetail = {
  code: "feature_not_available";
  feature: CapabilityDeniedFeature;
  plan: { id: string; code: string; name: string };
  message: string;
};

export type PaginatedPlatformOrganizations = {
  total: number;
  items: PlatformOrganizationSummary[];
};

export type PlatformUserOrganization = {
  organization_id: string;
  organization_name: string;
  role: string;
  status: string;
};

export type PlatformUserStatus = "active" | "disabled";

export type PlatformUserSummary = {
  id: string;
  email: string;
  email_verified: boolean;
  status: PlatformUserStatus;
  platform_role: string | null;
  organizations_count: number;
  created_at: string | null;
};

export type PlatformUserDetail = {
  id: string;
  email: string;
  email_verified: boolean;
  status: PlatformUserStatus;
  platform_role: string | null;
  created_at: string | null;
  organizations: PlatformUserOrganization[];
};

export type PaginatedPlatformUsers = {
  total: number;
  items: PlatformUserSummary[];
};

export type PlatformUserActionResponse = {
  message: string;
};

export type PlatformAuditLogTargetType = "organization" | "user" | null;

export type PlatformAuditLogEntry = {
  id: string;
  action: string;
  actor_user_id: string | null;
  actor_email: string;
  target_type: PlatformAuditLogTargetType;
  target_organization_id: string | null;
  target_organization_name: string | null;
  target_user_id: string | null;
  target_user_email: string | null;
  reason: string;
  details: Record<string, unknown> | null;
  client_ip: string | null;
  created_at: string;
};

export type PaginatedPlatformAuditLog = {
  total: number;
  items: PlatformAuditLogEntry[];
};

// Phase 22 -- tenant-facing Audit Timeline. Distinct from
// PlatformAuditLogEntry above (platform-admin actions on
// organizations/users, a different privileged surface) -- this is the
// ordinary business-domain event trail (customer/product/quote/invoice
// lifecycle transitions) scoped to a single organization.
export type AuditEntry = {
  id: string;
  organization_id: string;
  actor_user_id: string | null;
  actor_email: string | null;
  event_type: string;
  resource_type: string;
  resource_id: string;
  metadata: Record<string, unknown> | null;
  created_at: string;
};

export type PaginatedAuditEntries = {
  total: number;
  items: AuditEntry[];
};

// Phase 15A -- Organization API Keys. The wire-facing permission strings
// match app.api_key_permissions.ApiKeyPermission exactly (dotted,
// plural-noun form -- "customers.read", not "customer.read" like the
// browser-session Permission enum).
export type ApiKeyPermission =
  | "customers.read"
  | "customers.write"
  | "products.read"
  | "products.write"
  | "quotes.read"
  | "quotes.write"
  | "invoices.read"
  | "invoices.write"
  | "assistant.execute";

export const API_KEY_PERMISSIONS: ApiKeyPermission[] = [
  "customers.read",
  "customers.write",
  "products.read",
  "products.write",
  "quotes.read",
  "quotes.write",
  "invoices.read",
  "invoices.write",
  "assistant.execute",
];

export type ApiKeyStatus = "active" | "revoked" | "expired";

export type ApiKey = {
  id: string;
  organization_id: string;
  name: string;
  description: string;
  prefix: string;
  permissions: ApiKeyPermission[];
  status: ApiKeyStatus;
  created_by: string | null;
  created_at: string;
  expires_at: string | null;
  last_used_at: string | null;
  last_used_ip: string | null;
  revoked_at: string | null;
  revoked_by: string | null;
};

/** Only ever returned by create/rotate -- the one and only time the
 * complete, usable secret exists in a response body. Never returned by
 * GET/list. */
export type ApiKeyCreated = ApiKey & { api_key: string };

export type ApiKeyCreateRequest = {
  name: string;
  description: string;
  permissions: ApiKeyPermission[];
  expires_at: string | null;
};

// Phase 15B -- Outbound Webhooks. `subscribed_events` wire values match
// app.webhook_event_type.WebhookEventType exactly ("customer.created",
// ...), plus the special value "*" meaning "every event, including ones
// added in the future."
export const WEBHOOK_WILDCARD_EVENT = "*" as const;

export type WebhookEventCatalogEntry = {
  event_type: string;
  domain: string;
};

export type WebhookEndpoint = {
  id: string;
  organization_id: string;
  url: string;
  description: string;
  subscribed_events: string[];
  enabled: boolean;
  active: boolean;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  last_rotated_at: string | null;
};

/** Only ever returned by create/rotate-secret -- the one and only time
 * the complete signing secret exists in a response body. Never returned
 * by GET/list. */
export type WebhookEndpointCreated = WebhookEndpoint & { secret: string };

export type WebhookEndpointCreateRequest = {
  url: string;
  description: string;
  subscribed_events: string[];
};

export type WebhookEndpointUpdateRequest = {
  url?: string;
  description?: string;
  subscribed_events?: string[];
};

export type WebhookDeliveryStatus = "pending" | "succeeded" | "failed";
export type WebhookDeliveryTrigger = "automatic" | "manual_resend" | "automatic_retry";

export type WebhookDelivery = {
  id: string;
  organization_id: string;
  event_id: string;
  endpoint_id: string;
  status: WebhookDeliveryStatus;
  trigger: WebhookDeliveryTrigger;
  attempt_number: number;
  request_url: string;
  response_status_code: number | null;
  response_body_snippet: string | null;
  error_message: string | null;
  duration_ms: number | null;
  attempted_at: string | null;
  next_retry_at: string | null;
  created_at: string;
};

export type WebhookEvent = {
  id: string;
  organization_id: string;
  event_type: string;
  object_type: string;
  object_id: string;
  payload: Record<string, unknown>;
  created_at: string;
};

export type WebhookDeliveryDetail = WebhookDelivery & {
  request_headers: Record<string, string> | null;
  event: WebhookEvent;
};

export type PaginatedWebhookDeliveries = {
  total: number;
  items: WebhookDelivery[];
};

// Phase 15C -- Platform Admin Background Jobs visibility. Wire values
// match app.job_status.JobStatus / app.job_type.JobType exactly.
export type BackgroundJobStatus =
  | "pending"
  | "claimed"
  | "running"
  | "retry_scheduled"
  | "succeeded"
  | "permanently_failed"
  | "cancelled";

export type PlatformBackgroundJobEntry = {
  id: string;
  organization_id: string | null;
  job_type: string;
  status: BackgroundJobStatus;
  queue: string;
  priority: number;
  attempts: number;
  max_attempts: number;
  available_at: string;
  claimed_at: string | null;
  claimed_by: string | null;
  lease_expires_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  failed_at: string | null;
  last_error_code: string | null;
  last_error_message: string | null;
  result_summary: string | null;
  created_at: string;
  updated_at: string;
};

export type PlatformBackgroundJobDetail = PlatformBackgroundJobEntry & {
  payload: Record<string, unknown>;
  idempotency_key: string | null;
};

export type PaginatedPlatformBackgroundJobsResponse = {
  total: number;
  items: PlatformBackgroundJobEntry[];
};

export type PlatformJobActionRequest = {
  reason: string;
};

// Phase 20: event-driven notifications (in-app inbox + email preference)
export type Notification = {
  id: string;
  event_type: string;
  title: string;
  body: string;
  object_type: string;
  object_id: string;
  read_at: string | null;
  created_at: string;
};

export type PaginatedNotificationsResponse = {
  total: number;
  unread_count: number;
  items: Notification[];
};

export type NotificationPreference = {
  email_enabled: boolean;
};

// Phase 23: experimental WhatsApp AI assistant (Settings -> WhatsApp).
// See app/whatsapp/schemas.py -- these mirror that module's response
// shapes exactly.
export type WhatsAppConnectionState =
  | "disconnected"
  | "connecting"
  | "qr_required"
  | "connected"
  | "session_expired";

export type WhatsAppConnectionResponse = {
  state: WhatsAppConnectionState;
  connected_phone_number: string | null;
  last_heartbeat_at: string | null;
};

export type WhatsAppQuotaResponse = {
  used: number;
  limit: number | null;
  unlimited: boolean;
};

export type WhatsAppStatusResponse = {
  transport_enabled: boolean;
  transport_configured: boolean;
  plan_allows_whatsapp: boolean;
  plan_allows_voice_messages: boolean;
  connection: WhatsAppConnectionResponse;
  whatsapp_users_quota: WhatsAppQuotaResponse;
  whatsapp_actions_quota: WhatsAppQuotaResponse;
};

export type WhatsAppIdentityStatus = "pending" | "verified" | "disabled";

export type WhatsAppIdentityResponse = {
  id: string;
  user_id: string;
  user_email: string;
  normalized_phone_number: string;
  status: WhatsAppIdentityStatus;
  verified_at: string | null;
  last_message_at: string | null;
  created_at: string;
};

export type WhatsAppIdentityListResponse = {
  items: WhatsAppIdentityResponse[];
};

export type WhatsAppLinkRequest = {
  phone_number: string;
};

/** The one and only response that ever carries the raw verification code
 * -- see WhatsAppLinkResponse's own docstring. Never persist this beyond
 * the component state needed to display it once. */
export type WhatsAppLinkResponse = {
  identity_id: string;
  normalized_phone_number: string;
  status: WhatsAppIdentityStatus;
  verification_code: string;
  verification_expires_at: string;
};

export type WhatsAppQrResponse = {
  qr_data_base64: string;
  expires_at: string;
};

export type WhatsAppCommandHistoryItemResponse = {
  id: string;
  message_type: "text" | "audio";
  command_action: string | null;
  status: string;
  failure_code: string | null;
  created_at: string;
};

export type WhatsAppCommandHistoryResponse = {
  items: WhatsAppCommandHistoryItemResponse[];
};

export type UpdateNotificationPreferenceRequest = {
  email_enabled: boolean;
};
