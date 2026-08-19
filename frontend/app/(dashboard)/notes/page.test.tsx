import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setAuthSession } from "@/lib/auth-storage";
import type { AdjustmentNote, PaginatedAdjustmentNotes } from "@/lib/types";
import { renderWithProviders, screen, waitFor } from "@/tests/test-utils";

import NotesListPage from "./page";

vi.mock("next/navigation", () => ({
  useParams: () => ({}),
}));

const apiFetchMock = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, apiFetch: (...args: unknown[]) => apiFetchMock(...args) };
});

function note(overrides: Partial<AdjustmentNote>): AdjustmentNote {
  return {
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
    ...overrides,
  };
}

const CREDIT_NOTE = note({});
const DEBIT_NOTE = note({
  id: "note-2",
  note_type: "debit",
  note_number: "DN-000001",
  customer_name: "Beta LLC",
  total: "30.00",
});

function mockList(items: AdjustmentNote[]) {
  const data: PaginatedAdjustmentNotes = { items, total: items.length, limit: 50, offset: 0 };
  apiFetchMock.mockImplementation((path: string) => {
    const p = String(path);
    if (p.includes("/adjustment-notes")) return Promise.resolve(data);
    return Promise.reject(new Error(`unexpected call: ${p}`));
  });
}

beforeEach(() => {
  apiFetchMock.mockReset();
  setAuthSession({
    token: "test-token",
    apiBaseUrl: "http://localhost:8000",
    organizationId: "org-1",
    userEmail: "self@example.com",
    organizationPermissions: ["invoice.create", "invoice.read"],
  });
});

describe("unified notes list page", () => {
  it("shows a loading skeleton before notes load", () => {
    apiFetchMock.mockImplementation(() => new Promise(() => {}));
    renderWithProviders(<NotesListPage />);
    expect(document.querySelectorAll('[aria-hidden="true"]').length).toBeGreaterThan(0);
  });

  it("shows an error state when notes fail to load", async () => {
    apiFetchMock.mockImplementation(() => Promise.reject(new Error("boom")));
    renderWithProviders(<NotesListPage />);
    await waitFor(() => {
      expect(screen.getAllByText(/could not load notes/i).length).toBeGreaterThan(0);
    });
  });

  it("shows the empty state when there are no notes", async () => {
    mockList([]);
    renderWithProviders(<NotesListPage />);
    await waitFor(() => {
      expect(screen.getByText(/no notes yet/i)).toBeInTheDocument();
    });
  });

  it("lists both credit and debit notes with type/status badges, signed totals, and a link to detail", async () => {
    mockList([CREDIT_NOTE, DEBIT_NOTE]);
    renderWithProviders(<NotesListPage />);
    await waitFor(() => expect(screen.getByText("CN-000001")).toBeInTheDocument());
    expect(screen.getByText("DN-000001")).toBeInTheDocument();
    // "Credit note"/"Debit note" also appear as <option> text in the type
    // filter select, so assert presence rather than uniqueness here.
    expect(screen.getAllByText("Credit note").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Debit note").length).toBeGreaterThan(0);
    // "Issued" also appears as a status filter <option>, so assert at
    // least the two row badges rather than an exact count.
    expect(screen.getAllByText("Issued").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText(/-.*UYU 50[.,]00/)).toBeInTheDocument();
    expect(screen.getByText(/\+.*UYU 30[.,]00/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "CN-000001" })).toHaveAttribute("href", "/notes/note-1");
  });

  it("filters by type via a query param sent to the API", async () => {
    const user = userEvent.setup();
    mockList([CREDIT_NOTE]);
    renderWithProviders(<NotesListPage />);
    await waitFor(() => expect(screen.getByText("CN-000001")).toBeInTheDocument());

    await user.selectOptions(screen.getByDisplayValue("All types"), "credit");

    await waitFor(() => {
      const lastCall = apiFetchMock.mock.calls.at(-1)?.[0] as string;
      expect(lastCall).toContain("note_type=credit");
    });
  });

  it("filters by status via a query param sent to the API", async () => {
    const user = userEvent.setup();
    mockList([CREDIT_NOTE]);
    renderWithProviders(<NotesListPage />);
    await waitFor(() => expect(screen.getByText("CN-000001")).toBeInTheDocument());

    await user.selectOptions(screen.getByDisplayValue("All statuses"), "void");

    await waitFor(() => {
      const lastCall = apiFetchMock.mock.calls.at(-1)?.[0] as string;
      expect(lastCall).toContain("status=void");
    });
  });

  it("filters client-side by note number or customer name via search", async () => {
    const user = userEvent.setup();
    mockList([CREDIT_NOTE, DEBIT_NOTE]);
    renderWithProviders(<NotesListPage />);
    await waitFor(() => expect(screen.getByText("CN-000001")).toBeInTheDocument());

    await user.type(screen.getByPlaceholderText(/search by number or customer/i), "Beta");

    await waitFor(() => {
      expect(screen.queryByText("CN-000001")).not.toBeInTheDocument();
      expect(screen.getByText("DN-000001")).toBeInTheDocument();
    });
  });
});
