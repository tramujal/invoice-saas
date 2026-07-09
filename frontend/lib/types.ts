import type { PaymentStatus } from "@/lib/payment-status";

export type InvoiceSummary = {
  id: string;
  customer_id: string | null;
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
  organization_id: string;
  created_by_user_id: string | null;
  customer_id: string | null;
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
};

/** Response from POST /auth/login and POST /auth/register */
export type AuthResponse = {
  access_token: string;
  token_type: string;
  user: AuthUser;
  organizations: OrganizationSummary[];
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
