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
  created_at: string;
  updated_at: string;
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
  line_items: InvoiceLineItemResponse[];
};

export type AuthUser = {
  id: string;
  email: string;
};

export type OrganizationSummary = {
  id: string;
  name: string;
  currency_code: string;
};

/** Response from POST /auth/login and POST /auth/register */
export type AuthResponse = {
  access_token: string;
  token_type: string;
  user: AuthUser;
  organizations: OrganizationSummary[];
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

/** Response from GET /organizations/{org}/dashboard */
export type DashboardData = {
  total_revenue: string;
  total_invoices: number;
  total_customers: number;
  pending_invoices: number;
  paid_invoices: number;
  overdue_invoices: number;
  revenue_this_month: string;
  revenue_last_month: string;
  revenue_growth_percent: string | null;
  recent_invoices: InvoiceSummary[];
};

export type MonthlySummaryPoint = {
  month: string;
  revenue: string;
  invoice_count: number;
};

export type PaymentStatusCountPoint = {
  status: PaymentStatus;
  count: number;
};

export type TopCustomerRevenue = {
  customer_id: string;
  customer_name: string;
  revenue: string;
};

/** Response from GET /organizations/{org}/dashboard/analytics */
export type DashboardAnalytics = {
  monthly_summary: MonthlySummaryPoint[];
  invoice_count_by_status: PaymentStatusCountPoint[];
  top_customers: TopCustomerRevenue[];
};
