import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setAuthSession } from "@/lib/auth-storage";
import type {
  AdjustmentNote,
  InvoiceCreatedResponse,
  InvoiceCreditability,
} from "@/lib/types";
import { renderWithProviders, screen, waitFor } from "@/tests/test-utils";

import InvoiceDetailPage from "./page";

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "invoice-1" }),
}));

const apiFetchMock = vi.fn();
const apiFetchBlobMock = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    apiFetch: (...args: unknown[]) => apiFetchMock(...args),
    apiFetchBlob: (...args: unknown[]) => apiFetchBlobMock(...args),
  };
});

const SINGLE_RATE_INVOICE: InvoiceCreatedResponse = {
  id: "invoice-1",
  invoice_number: "INV-000001",
  organization_id: "org-1",
  created_by_user_id: "user-1",
  customer_id: "cust-1",
  customer_name: "Acme Corp",
  subtotal: "100.00",
  tax_amount: "22.00",
  total: "122.00",
  payment_status: "pending",
  effective_payment_status: "pending",
  currency_code: "UYU",
  language: "en",
  due_date: "2026-09-01",
  line_items: [
    {
      id: "line-a",
      description: "Service A",
      quantity: "1",
      unit_price: "100.00",
      line_total: "100.00",
      tax_rate: "0.2200",
      product_id: null,
    },
  ],
  tax_groups: [{ rate: "0.2200", base: "100.00", tax: "22.00" }],
};

const MIXED_TAX_INVOICE: InvoiceCreatedResponse = {
  ...SINGLE_RATE_INVOICE,
  subtotal: "1700.00",
  tax_amount: "270.00",
  total: "1970.00",
  line_items: [
    {
      id: "line-a",
      description: "Service A",
      quantity: "1",
      unit_price: "1000.00",
      line_total: "1000.00",
      tax_rate: "0.2200",
      product_id: null,
    },
    {
      id: "line-b",
      description: "Product B",
      quantity: "1",
      unit_price: "500.00",
      line_total: "500.00",
      tax_rate: "0.1000",
      product_id: null,
    },
    {
      id: "line-c",
      description: "Exempt item",
      quantity: "1",
      unit_price: "200.00",
      line_total: "200.00",
      tax_rate: "0",
      product_id: null,
    },
  ],
  tax_groups: [
    { rate: "0.2200", base: "1000.00", tax: "220.00" },
    { rate: "0.1000", base: "500.00", tax: "50.00" },
    { rate: "0", base: "200.00", tax: "0.00" },
  ],
};

const NO_ADJUSTMENTS: InvoiceCreditability = {
  summary: {
    original_total: "122.00",
    credited_total: "0.00",
    debited_total: "0.00",
    adjusted_total: "122.00",
    remaining_creditable: "122.00",
    currency_code: "UYU",
    issued_credit_note_count: 0,
    issued_debit_note_count: 0,
  },
  lines: [],
};

const WITH_ADJUSTMENTS: InvoiceCreditability = {
  summary: {
    original_total: "122.00",
    credited_total: "50.00",
    debited_total: "10.00",
    adjusted_total: "82.00",
    remaining_creditable: "72.00",
    currency_code: "UYU",
    issued_credit_note_count: 1,
    issued_debit_note_count: 1,
  },
  lines: [],
};

const LINKED_NOTE: AdjustmentNote = {
  id: "note-1",
  organization_id: "org-1",
  source_invoice_id: "invoice-1",
  customer_id: "cust-1",
  customer_name: "Acme Corp",
  note_type: "credit",
  note_number: "CN-000001",
  status: "issued",
  reason: "Refund",
  issue_date: "2026-08-01",
  subtotal: "50.00",
  tax_amount: "0.00",
  total: "50.00",
  currency_code: "UYU",
  language: "en",
  issued_at: "2026-08-01T00:00:00Z",
  voided_at: null,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
  line_items: [],
  tax_groups: [],
};

function mockRoutes({
  invoice = SINGLE_RATE_INVOICE,
  creditability = NO_ADJUSTMENTS,
  notes = [] as AdjustmentNote[],
}: {
  invoice?: InvoiceCreatedResponse;
  creditability?: InvoiceCreditability;
  notes?: AdjustmentNote[];
} = {}) {
  apiFetchMock.mockImplementation((path: string) => {
    const p = String(path);
    if (p.includes("/creditability")) return Promise.resolve(creditability);
    if (p.includes("/adjustment-notes")) return Promise.resolve(notes);
    if (p.includes("/invoices/")) return Promise.resolve(invoice);
    return Promise.reject(new Error(`unexpected call: ${p}`));
  });
}

beforeEach(() => {
  apiFetchMock.mockReset();
  apiFetchBlobMock.mockReset();
  setAuthSession({
    token: "test-token",
    apiBaseUrl: "http://localhost:8000",
    organizationId: "org-1",
    userEmail: "self@example.com",
    organizationPermissions: ["invoice.create", "invoice.read", "invoice.send"],
  });
});

describe("invoice detail page", () => {
  it("shows a loading skeleton before the invoice loads", () => {
    apiFetchMock.mockImplementation(() => new Promise(() => {}));
    renderWithProviders(<InvoiceDetailPage />);
    expect(document.querySelectorAll('[aria-hidden="true"]').length).toBeGreaterThan(0);
  });

  it("shows an error state when the invoice fails to load", async () => {
    apiFetchMock.mockImplementation(() => Promise.reject(new Error("boom")));
    renderWithProviders(<InvoiceDetailPage />);
    await waitFor(() => {
      expect(screen.getByText(/back to invoices/i)).toBeInTheDocument();
    });
  });

  it("renders the invoice number, customer and single-rate totals without a per-line tax column", async () => {
    mockRoutes();
    renderWithProviders(<InvoiceDetailPage />);
    await waitFor(() => expect(screen.getByText("INV-000001")).toBeInTheDocument());
    expect(screen.getByText("Acme Corp")).toBeInTheDocument();
    expect(screen.getByText("Service A")).toBeInTheDocument();
    // Single-rate invoice: no per-line tax column header.
    expect(screen.queryAllByText(/22%/).length).toBe(0);
  });

  it("shows the grouped tax summary and per-line tax column for a mixed-tax invoice", async () => {
    mockRoutes({ invoice: MIXED_TAX_INVOICE });
    renderWithProviders(<InvoiceDetailPage />);
    await waitFor(() => expect(screen.getByText("Service A")).toBeInTheDocument());
    expect(screen.getByText("Product B")).toBeInTheDocument();
    expect(screen.getAllByText(/22%/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/10%/).length).toBeGreaterThan(0);
  });

  it("never relabels or mutates the original total, and shows it separately from the adjusted total", async () => {
    mockRoutes({ creditability: WITH_ADJUSTMENTS, notes: [LINKED_NOTE] });
    renderWithProviders(<InvoiceDetailPage />);
    await waitFor(() => expect(screen.getByText("INV-000001")).toBeInTheDocument());

    // Original total (from the invoice itself) stays 122.00.
    expect(screen.getAllByText(/122[.,]00/).length).toBeGreaterThan(0);
    // Adjusted total (82.00) is shown as a distinct, separate figure.
    expect(screen.getByText(/82[.,]00/)).toBeInTheDocument();
  });

  it("lists linked adjustment notes, each navigable to its own detail page", async () => {
    mockRoutes({ creditability: WITH_ADJUSTMENTS, notes: [LINKED_NOTE] });
    renderWithProviders(<InvoiceDetailPage />);
    await waitFor(() => expect(screen.getByText("CN-000001")).toBeInTheDocument());
    const link = screen.getByRole("link", { name: "CN-000001" });
    expect(link).toHaveAttribute("href", "/notes/note-1");
  });

  it("offers create credit/debit note actions when the user has permission", async () => {
    mockRoutes();
    renderWithProviders(<InvoiceDetailPage />);
    await waitFor(() => expect(screen.getByText("INV-000001")).toBeInTheDocument());
    expect(screen.getByRole("link", { name: /create credit note/i })).toHaveAttribute(
      "href",
      "/invoices/invoice-1/notes/new?type=credit"
    );
    expect(screen.getByRole("link", { name: /create debit note/i })).toHaveAttribute(
      "href",
      "/invoices/invoice-1/notes/new?type=debit"
    );
  });

  it("hides the adjustments panel entirely for an ordinary invoice with no notes and no create permission", async () => {
    setAuthSession({
      token: "test-token",
      apiBaseUrl: "http://localhost:8000",
      organizationId: "org-1",
      userEmail: "viewer@example.com",
      organizationPermissions: ["invoice.read"],
    });
    mockRoutes();
    renderWithProviders(<InvoiceDetailPage />);
    await waitFor(() => expect(screen.getByText("INV-000001")).toBeInTheDocument());
    expect(screen.queryByText(/create credit note/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/create debit note/i)).not.toBeInTheDocument();
  });

  it("downloads the invoice PDF on demand", async () => {
    const user = userEvent.setup();
    mockRoutes();
    const fakeBlob = new Blob(["%PDF"], { type: "application/pdf" });
    apiFetchBlobMock.mockResolvedValue(fakeBlob);
    vi.stubGlobal("URL", {
      ...URL,
      createObjectURL: vi.fn(() => "blob:fake"),
      revokeObjectURL: vi.fn(),
    });

    renderWithProviders(<InvoiceDetailPage />);
    await waitFor(() => expect(screen.getByText("INV-000001")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: /download pdf/i }));

    await waitFor(() => {
      expect(apiFetchBlobMock).toHaveBeenCalledWith(
        expect.stringContaining("invoices/invoice-1/pdf")
      );
    });

    vi.unstubAllGlobals();
  });
});
