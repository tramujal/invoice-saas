import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { setAuthSession } from "@/lib/auth-storage";
import type { AdjustmentNote } from "@/lib/types";
import { renderWithProviders, screen, waitFor } from "@/tests/test-utils";

import AdjustmentNoteDetailPage from "./page";

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "note-1" }),
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

function note(overrides: Partial<AdjustmentNote>): AdjustmentNote {
  return {
    id: "note-1",
    organization_id: "org-1",
    source_invoice_id: "invoice-1",
    customer_id: "cust-1",
    customer_name: "Acme Corp",
    note_type: "credit",
    note_number: "CN-000001",
    status: "draft",
    reason: "Refund",
    issue_date: null,
    subtotal: "50.00",
    tax_amount: "0.00",
    total: "50.00",
    currency_code: "UYU",
    language: "en",
    issued_at: null,
    voided_at: null,
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-01T00:00:00Z",
    line_items: [
      {
        id: "line-1",
        description: "Refund line",
        quantity: "1",
        unit_price: "50.00",
        line_total: "50.00",
        tax_rate: "0",
        source_invoice_line_item_id: "src-line-1",
      },
    ],
    tax_groups: [],
    ...overrides,
  };
}

const DRAFT_NOTE = note({});
const ISSUED_NOTE = note({ status: "issued", issue_date: "2026-08-01", issued_at: "2026-08-01T00:00:00Z" });
const VOID_NOTE = note({ status: "void", issue_date: "2026-08-01", voided_at: "2026-08-02T00:00:00Z" });

function mockGet(returned: AdjustmentNote) {
  apiFetchMock.mockImplementation((path: string) => {
    const p = String(path);
    if (p.includes("/adjustment-notes/note-1") && !p.includes("/issue") && !p.includes("/void") && !p.includes("/send-email")) {
      return Promise.resolve(returned);
    }
    return Promise.reject(new Error(`unexpected call: ${p}`));
  });
}

beforeEach(() => {
  apiFetchMock.mockReset();
  apiFetchBlobMock.mockReset();
  vi.restoreAllMocks();
  setAuthSession({
    token: "test-token",
    apiBaseUrl: "http://localhost:8000",
    organizationId: "org-1",
    userEmail: "self@example.com",
    organizationPermissions: ["invoice.create", "invoice.read", "invoice.send"],
  });
});

describe("note detail page", () => {
  it("shows a loading skeleton before the note loads", () => {
    apiFetchMock.mockImplementation(() => new Promise(() => {}));
    renderWithProviders(<AdjustmentNoteDetailPage />);
    expect(document.querySelectorAll('[aria-hidden="true"]').length).toBeGreaterThan(0);
  });

  it("shows an error state when the note fails to load", async () => {
    apiFetchMock.mockImplementation(() => Promise.reject(new Error("boom")));
    renderWithProviders(<AdjustmentNoteDetailPage />);
    await waitFor(() => {
      expect(screen.getByText(/note not found/i)).toBeInTheDocument();
    });
  });

  it("draft status: offers Issue and Delete, hides PDF/send/void", async () => {
    mockGet(DRAFT_NOTE);
    renderWithProviders(<AdjustmentNoteDetailPage />);
    await waitFor(() => expect(screen.getByText("CN-000001")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Issue" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /download pdf/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /send by email/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /void/i })).not.toBeInTheDocument();
  });

  it("issued status: offers Download PDF, Send by email and Void when permitted", async () => {
    mockGet(ISSUED_NOTE);
    renderWithProviders(<AdjustmentNoteDetailPage />);
    await waitFor(() => expect(screen.getByText("CN-000001")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /download pdf/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /send by email/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Void" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Issue" })).not.toBeInTheDocument();
  });

  it("hides Send by email when the user lacks invoice.send permission", async () => {
    setAuthSession({
      token: "test-token",
      apiBaseUrl: "http://localhost:8000",
      organizationId: "org-1",
      userEmail: "no-send@example.com",
      organizationPermissions: ["invoice.create", "invoice.read"],
    });
    mockGet(ISSUED_NOTE);
    renderWithProviders(<AdjustmentNoteDetailPage />);
    await waitFor(() => expect(screen.getByText("CN-000001")).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: /send by email/i })).not.toBeInTheDocument();
  });

  it("void status: read-only, no action buttons", async () => {
    mockGet(VOID_NOTE);
    renderWithProviders(<AdjustmentNoteDetailPage />);
    await waitFor(() => expect(screen.getByText("CN-000001")).toBeInTheDocument());
    expect(screen.getByText(/no longer affects the invoice/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Issue" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /download pdf/i })).not.toBeInTheDocument();
  });

  it("issuing a draft note calls the issue endpoint and updates the displayed status", async () => {
    const user = userEvent.setup();
    apiFetchMock.mockImplementation((path: string, init?: RequestInit) => {
      const p = String(path);
      if (p.includes("/issue") && init?.method === "POST") return Promise.resolve(ISSUED_NOTE);
      if (p.includes("/adjustment-notes/note-1")) return Promise.resolve(DRAFT_NOTE);
      return Promise.reject(new Error(`unexpected call: ${p}`));
    });
    renderWithProviders(<AdjustmentNoteDetailPage />);
    await waitFor(() => expect(screen.getByText("CN-000001")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "Issue" }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        expect.stringContaining("adjustment-notes/note-1/issue"),
        expect.objectContaining({ method: "POST" })
      );
      expect(screen.getByRole("button", { name: /download pdf/i })).toBeInTheDocument();
    });
  });

  it("voiding an issued note asks for confirmation and calls the void endpoint", async () => {
    const user = userEvent.setup();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    apiFetchMock.mockImplementation((path: string, init?: RequestInit) => {
      const p = String(path);
      if (p.includes("/void") && init?.method === "POST") return Promise.resolve(VOID_NOTE);
      if (p.includes("/adjustment-notes/note-1")) return Promise.resolve(ISSUED_NOTE);
      return Promise.reject(new Error(`unexpected call: ${p}`));
    });
    renderWithProviders(<AdjustmentNoteDetailPage />);
    await waitFor(() => expect(screen.getByText("CN-000001")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "Void" }));

    await waitFor(() => {
      expect(window.confirm).toHaveBeenCalled();
      expect(apiFetchMock).toHaveBeenCalledWith(
        expect.stringContaining("adjustment-notes/note-1/void"),
        expect.objectContaining({ method: "POST" })
      );
    });
  });

  it("does not void when the confirmation is declined", async () => {
    const user = userEvent.setup();
    vi.spyOn(window, "confirm").mockReturnValue(false);
    mockGet(ISSUED_NOTE);
    renderWithProviders(<AdjustmentNoteDetailPage />);
    await waitFor(() => expect(screen.getByText("CN-000001")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "Void" }));

    await waitFor(() => expect(window.confirm).toHaveBeenCalled());
    expect(apiFetchMock).not.toHaveBeenCalledWith(
      expect.stringContaining("/void"),
      expect.objectContaining({ method: "POST" })
    );
  });

  it("deletes a draft note after confirmation", async () => {
    const user = userEvent.setup();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    apiFetchMock.mockImplementation((path: string, init?: RequestInit) => {
      const p = String(path);
      if (p === "/organizations/org-1/adjustment-notes/note-1" && init?.method === "DELETE") {
        return Promise.resolve(undefined);
      }
      if (p.includes("/adjustment-notes/note-1")) return Promise.resolve(DRAFT_NOTE);
      return Promise.reject(new Error(`unexpected call: ${p}`));
    });
    renderWithProviders(<AdjustmentNoteDetailPage />);
    await waitFor(() => expect(screen.getByText("CN-000001")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "Delete" }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        expect.stringContaining("adjustment-notes/note-1"),
        expect.objectContaining({ method: "DELETE" })
      );
    });
  });

  it("downloads the note PDF on demand", async () => {
    const user = userEvent.setup();
    mockGet(ISSUED_NOTE);
    apiFetchBlobMock.mockResolvedValue(new Blob(["%PDF"], { type: "application/pdf" }));
    vi.stubGlobal("URL", { ...URL, createObjectURL: vi.fn(() => "blob:fake"), revokeObjectURL: vi.fn() });

    renderWithProviders(<AdjustmentNoteDetailPage />);
    await waitFor(() => expect(screen.getByText("CN-000001")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: /download pdf/i }));

    await waitFor(() => {
      expect(apiFetchBlobMock).toHaveBeenCalledWith(expect.stringContaining("adjustment-notes/note-1/pdf"));
    });

    vi.unstubAllGlobals();
  });

  it("sends the note by email and shows a success toast", async () => {
    const user = userEvent.setup();
    apiFetchMock.mockImplementation((path: string, init?: RequestInit) => {
      const p = String(path);
      if (p.includes("/send-email") && init?.method === "POST") {
        return Promise.resolve({ sent_to: "customer@example.com", note_number: "CN-000001" });
      }
      if (p.includes("/adjustment-notes/note-1")) return Promise.resolve(ISSUED_NOTE);
      return Promise.reject(new Error(`unexpected call: ${p}`));
    });
    renderWithProviders(<AdjustmentNoteDetailPage />);
    await waitFor(() => expect(screen.getByText("CN-000001")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: /send by email/i }));

    await waitFor(() => {
      expect(screen.getByText(/sent to customer@example\.com/i)).toBeInTheDocument();
    });
  });

  it("shows a specific error when the customer has no email on file", async () => {
    const user = userEvent.setup();
    apiFetchMock.mockImplementation((path: string, init?: RequestInit) => {
      const p = String(path);
      if (p.includes("/send-email") && init?.method === "POST") {
        return Promise.reject(
          new ApiError("no email", 422, { detail: { code: "customer_email_missing", message: "nope" } })
        );
      }
      if (p.includes("/adjustment-notes/note-1")) return Promise.resolve(ISSUED_NOTE);
      return Promise.reject(new Error(`unexpected call: ${p}`));
    });
    renderWithProviders(<AdjustmentNoteDetailPage />);
    await waitFor(() => expect(screen.getByText("CN-000001")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: /send by email/i }));

    await waitFor(() => {
      expect(screen.getByText(/no email address on file/i)).toBeInTheDocument();
    });
  });

  it("shows a link to the related invoice", async () => {
    mockGet(ISSUED_NOTE);
    renderWithProviders(<AdjustmentNoteDetailPage />);
    await waitFor(() => expect(screen.getByText("CN-000001")).toBeInTheDocument());
    expect(screen.getByRole("link", { name: /view invoice/i })).toHaveAttribute(
      "href",
      "/invoices/invoice-1"
    );
  });
});
