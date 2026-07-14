import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PublicQuote } from "@/lib/types";
import { renderWithProviders, screen, waitFor } from "@/tests/test-utils";

import PublicQuotePage from "./page";

vi.mock("next/navigation", () => ({
  useParams: () => ({ token: "quote-token-abc" }),
}));

const publicGetMock = vi.fn();
const authRequestMock = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    publicGet: (...args: unknown[]) => publicGetMock(...args),
    authRequest: (...args: unknown[]) => authRequestMock(...args),
  };
});

function baseQuote(overrides: Partial<PublicQuote> = {}): PublicQuote {
  return {
    quote_number: "QUO-000001",
    organization_name: "Acme Inc",
    customer_name: "Jane Customer",
    subtotal: "100.00",
    tax_rate: "0",
    tax_amount: "0.00",
    total: "100.00",
    effective_status: "sent",
    currency_code: "USD",
    language: "en",
    issue_date: "2026-01-01",
    expiry_date: null,
    notes: "",
    line_items: [
      { description: "Consulting", quantity: "1", unit_price: "100.00", line_total: "100.00" },
    ],
    ...overrides,
  };
}

beforeEach(() => {
  window.localStorage.clear();
  publicGetMock.mockReset();
  authRequestMock.mockReset();
});

describe("Public quote page", () => {
  it("shows accept/reject buttons for a sent quote and accepts successfully", async () => {
    publicGetMock.mockResolvedValue(baseQuote());
    authRequestMock.mockResolvedValue({ status: "accepted" });
    const user = userEvent.setup();
    renderWithProviders(<PublicQuotePage />);

    await waitFor(() => expect(screen.getByText("Acme Inc")).toBeInTheDocument());
    const acceptButton = screen.getByRole("button", { name: "Accept Quote" });
    await user.click(acceptButton);

    await waitFor(() => expect(authRequestMock).toHaveBeenCalledWith(
      expect.any(String),
      "/quotes/public/quote-token-abc/accept",
      undefined
    ));
  });

  it("shows an already-decided message instead of action buttons once accepted", async () => {
    publicGetMock.mockResolvedValue(baseQuote({ effective_status: "accepted" }));
    renderWithProviders(<PublicQuotePage />);

    await waitFor(() => expect(screen.getByText("Acme Inc")).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "Accept Quote" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reject Quote" })).not.toBeInTheDocument();
    expect(screen.getByText(/already/i)).toBeInTheDocument();
  });

  it("renders a not-found message for an unknown token", async () => {
    const { ApiError } = await import("@/lib/api");
    publicGetMock.mockRejectedValue(new ApiError("Quote not found", 404));
    renderWithProviders(<PublicQuotePage />);

    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
  });
});
