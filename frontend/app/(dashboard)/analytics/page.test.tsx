import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { setAuthSession } from "@/lib/auth-storage";
import type { KpiSnapshot } from "@/lib/types";
import { renderWithProviders, screen, waitFor, within } from "@/tests/test-utils";

import AnalyticsPage from "./page";

const routerReplace = vi.fn();
let currentSearch = "";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: routerReplace, push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(currentSearch),
}));

const apiFetchMock = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    apiFetch: (...args: unknown[]) => apiFetchMock(...args),
  };
});

function makeSnapshot(overrides: Partial<KpiSnapshot> = {}): KpiSnapshot {
  return {
    window: { kind: "current_month", start: "2026-07-01T00:00:00Z", end: "2026-08-01T00:00:00Z" },
    invoice_counts: { total: 3, pending: 2, paid: 0, overdue: 1 },
    revenue_by_currency: { USD: "200.00" },
    revenue_breakdown: [
      { currency_code: "USD", total: "200.00", paid: "0.00", outstanding: "200.00", overdue: "100.00" },
    ],
    average_invoice_value: { USD: "100.00" },
    customer_growth: 2,
    customer_retention: { total_invoiced_customers: 2, repeat_customers: 1, retention_rate_percent: 50 },
    quote_acceptance_rate_percent: 75,
    average_payment_time: { available: true, average_days: 4.2, reason: null },
    ...overrides,
  };
}

beforeEach(() => {
  apiFetchMock.mockReset();
  routerReplace.mockReset();
  currentSearch = "";
  setAuthSession({
    token: "test-token",
    apiBaseUrl: "https://api.test",
    organizationId: "org-1",
    organizationPermissions: ["dashboard.view"],
  });
});

describe("AnalyticsPage", () => {
  it("renders the KPI snapshot for the default current_month window", async () => {
    apiFetchMock.mockResolvedValue(makeSnapshot());
    renderWithProviders(<AnalyticsPage />);

    await waitFor(() => expect(apiFetchMock).toHaveBeenCalled());
    expect(apiFetchMock.mock.calls[0][0]).toContain("window=current_month");

    await waitFor(() => expect(screen.getByText("3")).toBeInTheDocument());
    expect(screen.getByText("+2")).toBeInTheDocument();
    expect(screen.getByText("4.2 days")).toBeInTheDocument();
  });

  it("reads the initial window from the URL and refetches when the selector changes", async () => {
    currentSearch = "window=last_7_days";
    apiFetchMock.mockResolvedValue(makeSnapshot());
    renderWithProviders(<AnalyticsPage />);

    await waitFor(() => expect(apiFetchMock).toHaveBeenCalled());
    expect(apiFetchMock.mock.calls[0][0]).toContain("window=last_7_days");

    apiFetchMock.mockClear();
    apiFetchMock.mockResolvedValue(makeSnapshot());
    const select = screen.getByLabelText("Time period") as HTMLSelectElement;
    select.value = "current_year";
    select.dispatchEvent(new Event("change", { bubbles: true }));

    await waitFor(() => expect(apiFetchMock).toHaveBeenCalled());
    expect(apiFetchMock.mock.calls[0][0]).toContain("window=current_year");
    expect(routerReplace).toHaveBeenCalledWith(expect.stringContaining("window=current_year"));
  });

  it("never sums revenue across currencies -- each currency gets its own row", async () => {
    apiFetchMock.mockResolvedValue(
      makeSnapshot({
        revenue_by_currency: { USD: "222.00", EUR: "111.00" },
        revenue_breakdown: [
          { currency_code: "USD", total: "222.00", paid: "22.00", outstanding: "200.00", overdue: "0.00" },
          { currency_code: "EUR", total: "111.00", paid: "11.00", outstanding: "100.00", overdue: "0.00" },
        ],
        average_invoice_value: { USD: "74.00", EUR: "55.50" },
      })
    );
    renderWithProviders(<AnalyticsPage />);

    const table = await screen.findByRole("table");
    const usdRow = within(table).getByText("USD").closest("tr")!;
    const eurRow = within(table).getByText("EUR").closest("tr")!;
    const usdCells = within(usdRow).getAllByRole("cell");
    const eurCells = within(eurRow).getAllByRole("cell");
    // Column order: Currency, Total, Paid, Outstanding, Overdue, Avg invoice.
    // formatMoney (lib/money.ts) renders via toLocaleString, so the exact
    // separator is environment-dependent -- match on the numeric value.
    expect(usdCells[1].textContent).toMatch(/^222[.,]00$/);
    expect(eurCells[1].textContent).toMatch(/^111[.,]00$/);
    // No combined/summed total row exists anywhere in the table.
    expect(within(table).queryByText(/^333[.,]00$/)).not.toBeInTheDocument();
  });

  it("shows a translated unavailable message, never '0 days', when average payment time is unavailable", async () => {
    apiFetchMock.mockResolvedValue(
      makeSnapshot({
        average_payment_time: {
          available: false,
          average_days: null,
          reason: "Invoice has no paid_at timestamp -- average payment time cannot be computed yet.",
        },
      })
    );
    renderWithProviders(<AnalyticsPage />);

    await waitFor(() => expect(screen.getByText("Not enough data yet")).toBeInTheDocument());
    expect(screen.queryByText("0 days")).not.toBeInTheDocument();
    expect(screen.queryByText(/paid_at/)).not.toBeInTheDocument();
  });

  it("never coerces a null retention rate to 0%", async () => {
    apiFetchMock.mockResolvedValue(
      makeSnapshot({
        customer_retention: { total_invoiced_customers: 0, repeat_customers: 0, retention_rate_percent: null },
      })
    );
    renderWithProviders(<AnalyticsPage />);

    await waitFor(() => expect(screen.getAllByText("Not enough data yet").length).toBeGreaterThan(0));
    expect(screen.queryByText("0%")).not.toBeInTheDocument();
    expect(screen.queryByText("0.0%")).not.toBeInTheDocument();
  });

  it("never coerces a null quote acceptance rate to 0%", async () => {
    apiFetchMock.mockResolvedValue(makeSnapshot({ quote_acceptance_rate_percent: null }));
    renderWithProviders(<AnalyticsPage />);

    await waitFor(() => expect(screen.getAllByText("Not enough data yet").length).toBeGreaterThan(0));
  });

  it("renders a graceful all-zero snapshot for an organization with no data yet", async () => {
    apiFetchMock.mockResolvedValue(
      makeSnapshot({
        invoice_counts: { total: 0, pending: 0, paid: 0, overdue: 0 },
        revenue_by_currency: {},
        revenue_breakdown: [],
        average_invoice_value: {},
        customer_growth: 0,
        customer_retention: { total_invoiced_customers: 0, repeat_customers: 0, retention_rate_percent: null },
        quote_acceptance_rate_percent: null,
        average_payment_time: { available: false, average_days: null, reason: "no data" },
      })
    );
    renderWithProviders(<AnalyticsPage />);

    await waitFor(() => expect(screen.getByText("No revenue yet")).toBeInTheDocument());
    expect(screen.getAllByText("0").length).toBeGreaterThan(0);
  });

  it("shows a translated, generic error message on a failure -- never raw backend text", async () => {
    apiFetchMock.mockRejectedValue(new ApiError("Request failed (500)", 500, { detail: "boom" }));
    renderWithProviders(<AnalyticsPage />);

    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByRole("alert")).toHaveTextContent("Failed to load analytics");
    expect(screen.queryByText("boom")).not.toBeInTheDocument();
  });

  it("shows a permission-denied message on a 403, not raw backend text", async () => {
    apiFetchMock.mockRejectedValue(
      new ApiError("Request failed (403)", 403, { detail: { code: "forbidden" } })
    );
    renderWithProviders(<AnalyticsPage />);

    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByRole("alert")).toHaveTextContent(
      "You don't have permission to view analytics for this organization."
    );
  });

  it("shows loading skeletons without unmounting the page shell", async () => {
    let resolveFetch: (value: KpiSnapshot) => void = () => {};
    apiFetchMock.mockReturnValue(
      new Promise<KpiSnapshot>((resolve) => {
        resolveFetch = resolve;
      })
    );
    renderWithProviders(<AnalyticsPage />);

    // The page shell (heading, window selector) is present immediately,
    // even before the first response arrives.
    expect(screen.getByRole("heading", { name: "Analytics" })).toBeInTheDocument();
    expect(screen.getByLabelText("Time period")).toBeInTheDocument();

    resolveFetch(makeSnapshot());
    await waitFor(() => expect(screen.getByText("3")).toBeInTheDocument());
  });
});
