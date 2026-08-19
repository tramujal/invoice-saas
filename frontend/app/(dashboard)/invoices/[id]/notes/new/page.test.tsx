import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { setAuthSession } from "@/lib/auth-storage";
import type { InvoiceCreditability } from "@/lib/types";
import { renderWithProviders, screen, waitFor, within } from "@/tests/test-utils";

import CreateNotePage from "./page";

const pushMock = vi.fn();
let searchParamsValue = new URLSearchParams("type=credit");

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "invoice-1" }),
  useRouter: () => ({ push: pushMock }),
  useSearchParams: () => searchParamsValue,
}));

const apiFetchMock = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, apiFetch: (...args: unknown[]) => apiFetchMock(...args) };
});

const MIXED_CREDITABILITY: InvoiceCreditability = {
  summary: {
    original_total: "1970.00",
    credited_total: "0.00",
    debited_total: "0.00",
    adjusted_total: "1970.00",
    remaining_creditable: "1970.00",
    currency_code: "UYU",
    issued_credit_note_count: 0,
    issued_debit_note_count: 0,
  },
  lines: [
    {
      invoice_line_item_id: "line-a",
      description: "Service A",
      quantity: "1",
      unit_price: "1000.00",
      line_total: "1000.00",
      tax_rate: "0.2200",
      credited_total: "0.00",
      remaining_creditable: "1000.00",
    },
    {
      invoice_line_item_id: "line-b",
      description: "Product B",
      quantity: "1",
      unit_price: "500.00",
      line_total: "500.00",
      tax_rate: "0.1000",
      credited_total: "0.00",
      remaining_creditable: "500.00",
    },
  ],
};

function mockCreditability(data: InvoiceCreditability = MIXED_CREDITABILITY) {
  apiFetchMock.mockImplementation((path: string, init?: RequestInit) => {
    const p = String(path);
    if (p.includes("/creditability")) return Promise.resolve(data);
    if (p.includes("/adjustment-notes/") && init?.method === "POST") {
      return Promise.resolve({ id: "note-1", note_number: "CN-000001" });
    }
    return Promise.reject(new Error(`unexpected call: ${p}`));
  });
}

beforeEach(() => {
  apiFetchMock.mockReset();
  pushMock.mockReset();
  searchParamsValue = new URLSearchParams("type=credit");
  setAuthSession({
    token: "test-token",
    apiBaseUrl: "http://localhost:8000",
    organizationId: "org-1",
    userEmail: "self@example.com",
    organizationPermissions: ["invoice.create", "invoice.read"],
  });
});

describe("credit note creation", () => {
  it("shows the source invoice's remaining creditable amount", async () => {
    mockCreditability();
    renderWithProviders(<CreateNotePage />);
    await waitFor(() => {
      expect(screen.getByTestId("remaining-creditable")).toHaveTextContent(/1[.,]970[.,]00/);
    });
  });

  it("prefills each line's tax rate from the source invoice line", async () => {
    mockCreditability();
    renderWithProviders(<CreateNotePage />);
    await waitFor(() => expect(screen.getByText("Service A")).toBeInTheDocument());
    expect(screen.getByText(/22%/)).toBeInTheDocument();
    expect(screen.getByText(/10%/)).toBeInTheDocument();
  });

  it("supports a partial credit on one line", async () => {
    const user = userEvent.setup();
    mockCreditability();
    renderWithProviders(<CreateNotePage />);
    await waitFor(() => expect(screen.getByText("Service A")).toBeInTheDocument());

    const checkbox = screen.getByRole("checkbox", { name: /credit service a/i });
    await user.click(checkbox);
    const amountInputs = screen.getAllByLabelText(/amount to credit/i) as HTMLInputElement[];
    const amountInput = amountInputs.find((el) => !el.disabled)!;
    await user.clear(amountInput);
    await user.type(amountInput, "400");

    await waitFor(() => {
      expect(screen.getByTestId("note-total")).toHaveTextContent("488"); // 400 + 22%, locale-agnostic
    });
  });

  it("'credit full remaining balance' selects every line at its full amount", async () => {
    const user = userEvent.setup();
    mockCreditability();
    renderWithProviders(<CreateNotePage />);
    await waitFor(() => expect(screen.getByText("Service A")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: /credit full remaining balance/i }));

    await waitFor(() => {
      // 1000@22% + 500@10% = 1220 + 550 = 1770
      expect(screen.getByTestId("note-total")).toHaveTextContent(/1[.,]770/);
    });
  });

  it("shows the mixed-tax grouped summary", async () => {
    const user = userEvent.setup();
    mockCreditability();
    renderWithProviders(<CreateNotePage />);
    await waitFor(() => expect(screen.getByText("Service A")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: /credit full remaining balance/i }));

    await waitFor(() => {
      const summary = screen.getByTestId("note-total").closest("dl")!;
      expect(within(summary).getByText(/Tax 22%/)).toBeInTheDocument();
      expect(within(summary).getByText(/Tax 10%/)).toBeInTheDocument();
    });
  });

  it("prevents an obvious client-side over-credit before submitting", async () => {
    const user = userEvent.setup();
    mockCreditability();
    renderWithProviders(<CreateNotePage />);
    await waitFor(() => expect(screen.getByText("Service A")).toBeInTheDocument());

    const checkbox = screen.getByRole("checkbox", { name: /credit service a/i });
    await user.click(checkbox);
    const amountInputs = screen.getAllByLabelText(/amount to credit/i) as HTMLInputElement[];
    const amountInput = amountInputs.find((el) => !el.disabled)!;
    await user.clear(amountInput);
    await user.type(amountInput, "5000");

    const submit = screen.getByRole("button", { name: /create note/i });
    await waitFor(() => expect(submit).toBeDisabled());
  });

  it("renders the backend's over-credit error when the server rejects it", async () => {
    const user = userEvent.setup();
    apiFetchMock.mockImplementation((path: string, init?: RequestInit) => {
      const p = String(path);
      if (p.includes("/creditability")) return Promise.resolve(MIXED_CREDITABILITY);
      if (init?.method === "POST") {
        return Promise.reject(
          new ApiError("over credit", 409, { detail: { code: "over_credit", message: "nope" } })
        );
      }
      return Promise.reject(new Error("unexpected"));
    });
    renderWithProviders(<CreateNotePage />);
    await waitFor(() => expect(screen.getByText("Service A")).toBeInTheDocument());

    const checkbox = screen.getByRole("checkbox", { name: /credit service a/i });
    await user.click(checkbox);
    await user.click(screen.getByRole("button", { name: /create note/i }));

    await waitFor(() => {
      expect(screen.getAllByRole("alert")[0]).toHaveTextContent(/exceeds/i);
    });
  });
});

describe("debit note creation", () => {
  beforeEach(() => {
    searchParamsValue = new URLSearchParams("type=debit");
  });

  it("shows free-form lines instead of the invoice's own lines", async () => {
    mockCreditability();
    renderWithProviders(<CreateNotePage />);
    await waitFor(() => {
      expect(screen.getByText(/additional charges/i)).toBeInTheDocument();
    });
    expect(screen.queryByText("Service A")).not.toBeInTheDocument();
  });

  it("computes the total from a free-form line with tax", async () => {
    const user = userEvent.setup();
    mockCreditability();
    renderWithProviders(<CreateNotePage />);
    await waitFor(() => expect(screen.getByText(/additional charges/i)).toBeInTheDocument());

    const description = screen.getByLabelText(/description/i);
    await user.type(description, "Extra delivery");
    const priceInputs = screen.getAllByRole("spinbutton");
    const priceInput = priceInputs.find((el) => (el as HTMLInputElement).step === "0.01")!;
    await user.clear(priceInput);
    await user.type(priceInput, "100");

    await waitFor(() => {
      expect(screen.getByTestId("note-total")).toHaveTextContent("122");
    });
  });

  it("never offers a negative price or quantity (min=0 on both inputs)", async () => {
    mockCreditability();
    renderWithProviders(<CreateNotePage />);
    await waitFor(() => expect(screen.getByText(/additional charges/i)).toBeInTheDocument());
    const spinbuttons = screen.getAllByRole("spinbutton") as HTMLInputElement[];
    for (const input of spinbuttons) {
      expect(input.min).toBe("0");
    }
  });
});

describe("loading, empty and permission states", () => {
  it("shows a loading skeleton before the invoice loads", () => {
    apiFetchMock.mockImplementation(() => new Promise(() => {}));
    renderWithProviders(<CreateNotePage />);
    expect(document.querySelectorAll('[aria-hidden="true"]').length).toBeGreaterThan(0);
  });

  it("shows an error state when the invoice fails to load", async () => {
    apiFetchMock.mockImplementation(() => Promise.reject(new Error("boom")));
    renderWithProviders(<CreateNotePage />);
    await waitFor(() => {
      expect(screen.getByText(/back to invoice/i)).toBeInTheDocument();
    });
  });
});
