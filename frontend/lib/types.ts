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
