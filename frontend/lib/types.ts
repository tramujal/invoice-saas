import type { PaymentStatus } from "@/lib/payment-status";

export type InvoiceSummary = {
  id: string;
  invoice_number: string;
  customer_id: string | null;
  customer_name: string | null;
  subtotal: string;
  tax_amount: string;
  total: string;
  payment_status: PaymentStatus;
  /** Permanently pinned at creation — never re-derived from the
   * organization's current currency. */
  currency_code: string;
  /** Permanently pinned at creation — never re-derived from the
   * organization's current language. */
  language: string;
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
  currency_code: string;
  language: string;
  line_items: InvoiceLineItemResponse[];
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

/** Response from GET /organizations/{org}/dashboard/analytics */
export type DashboardAnalytics = {
  monthly_summary: MonthlySummaryPoint[];
  monthly_revenue_by_currency: MonthlyRevenuePoint[];
  invoice_count_by_status: PaymentStatusCountPoint[];
  top_customers: TopCustomerRevenue[];
};
