import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { setAuthSession } from "@/lib/auth-storage";
import type { KpiSnapshot, TrendSnapshot } from "@/lib/types";
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

function makeTrendSnapshot(overrides: Partial<TrendSnapshot> = {}): TrendSnapshot {
  return {
    comparison_kind: "current_month",
    granularity: "monthly",
    revenue_trend: {
      USD: {
        current: "200.00",
        previous: "100.00",
        absolute_difference: "100.00",
        percentage_difference: "100.00",
        direction: "up",
      },
    },
    invoice_count_trend: {
      current: "3.00",
      previous: "1.00",
      absolute_difference: "2.00",
      percentage_difference: "200.00",
      direction: "up",
    },
    customer_growth_trend: {
      current: "2.00",
      previous: "1.00",
      absolute_difference: "1.00",
      percentage_difference: "100.00",
      direction: "up",
    },
    quote_count_trend: {
      current: "1.00",
      previous: "1.00",
      absolute_difference: "0.00",
      percentage_difference: "0.00",
      direction: "flat",
    },
    revenue_series: [
      { period: "2026-06", value: "100.00", currency_code: "USD" },
      { period: "2026-07", value: "200.00", currency_code: "USD" },
    ],
    invoice_count_series: [
      { period: "2026-06", value: "1.00", currency_code: null },
      { period: "2026-07", value: "3.00", currency_code: null },
    ],
    customer_count_series: [
      { period: "2026-06", value: "1.00", currency_code: null },
      { period: "2026-07", value: "2.00", currency_code: null },
    ],
    quote_conversion_series: [
      { period: "2026-06", value: "0.00", currency_code: null },
      { period: "2026-07", value: "1.00", currency_code: null },
    ],
    revenue_forecast: {
      USD: {
        available: true,
        method: "simple_moving_average",
        forecast_value: "150.00",
        inputs: ["100.00", "200.00"],
        window_size: 2,
        reason: null,
      },
    },
    invoice_count_forecast: {
      available: true,
      method: "linear_trend",
      forecast_value: "5.00",
      inputs: ["1.00", "3.00"],
      window_size: null,
      reason: null,
    },
    ...overrides,
  };
}

/** Dispatches the mocked apiFetch by URL -- the page now makes two
 * independent requests (kpis + trends), so a single flat mockResolvedValue
 * is no longer enough to give each one its own realistic shape. */
function mockApiResponses(kpi: KpiSnapshot, trend: TrendSnapshot) {
  apiFetchMock.mockImplementation((path: unknown) => {
    if (typeof path === "string" && path.includes("/analytics/trends")) {
      return Promise.resolve(trend);
    }
    return Promise.resolve(kpi);
  });
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
    mockApiResponses(makeSnapshot(), makeTrendSnapshot());
    renderWithProviders(<AnalyticsPage />);

    await waitFor(() => expect(apiFetchMock).toHaveBeenCalled());
    expect(apiFetchMock.mock.calls.some((c) => String(c[0]).includes("window=current_month"))).toBe(
      true
    );

    await waitFor(() => expect(screen.getByText("Total invoices")).toBeInTheDocument());
    const totalInvoicesCard = screen.getByText("Total invoices").closest("article")!;
    expect(within(totalInvoicesCard).getByText("3")).toBeInTheDocument();
    expect(screen.getByText("+2")).toBeInTheDocument();
    expect(screen.getByText("4.2 days")).toBeInTheDocument();
  });

  it("reads the initial window from the URL and refetches when the selector changes", async () => {
    currentSearch = "window=last_7_days";
    mockApiResponses(makeSnapshot(), makeTrendSnapshot());
    renderWithProviders(<AnalyticsPage />);

    await waitFor(() => expect(apiFetchMock).toHaveBeenCalled());
    expect(apiFetchMock.mock.calls.some((c) => String(c[0]).includes("window=last_7_days"))).toBe(
      true
    );

    apiFetchMock.mockClear();
    mockApiResponses(makeSnapshot(), makeTrendSnapshot());
    const select = screen.getByLabelText("Time period") as HTMLSelectElement;
    select.value = "current_year";
    select.dispatchEvent(new Event("change", { bubbles: true }));

    await waitFor(() =>
      expect(apiFetchMock.mock.calls.some((c) => String(c[0]).includes("window=current_year"))).toBe(
        true
      )
    );
    expect(routerReplace).toHaveBeenCalledWith(expect.stringContaining("window=current_year"));
  });

  it("never sums revenue across currencies -- each currency gets its own row", async () => {
    mockApiResponses(
      makeSnapshot({
        revenue_by_currency: { USD: "222.00", EUR: "111.00" },
        revenue_breakdown: [
          { currency_code: "USD", total: "222.00", paid: "22.00", outstanding: "200.00", overdue: "0.00" },
          { currency_code: "EUR", total: "111.00", paid: "11.00", outstanding: "100.00", overdue: "0.00" },
        ],
        average_invoice_value: { USD: "74.00", EUR: "55.50" },
      }),
      makeTrendSnapshot()
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
    mockApiResponses(
      makeSnapshot({
        average_payment_time: {
          available: false,
          average_days: null,
          reason: "Invoice has no paid_at timestamp -- average payment time cannot be computed yet.",
        },
      }),
      makeTrendSnapshot()
    );
    renderWithProviders(<AnalyticsPage />);

    await waitFor(() => expect(screen.getByText("Not enough data yet")).toBeInTheDocument());
    expect(screen.queryByText("0 days")).not.toBeInTheDocument();
    expect(screen.queryByText(/paid_at/)).not.toBeInTheDocument();
  });

  it("never coerces a null retention rate to 0%", async () => {
    mockApiResponses(
      makeSnapshot({
        customer_retention: { total_invoiced_customers: 0, repeat_customers: 0, retention_rate_percent: null },
      }),
      makeTrendSnapshot()
    );
    renderWithProviders(<AnalyticsPage />);

    await waitFor(() => expect(screen.getAllByText("Not enough data yet").length).toBeGreaterThan(0));
    expect(screen.queryByText("0%")).not.toBeInTheDocument();
    expect(screen.queryByText("0.0%")).not.toBeInTheDocument();
  });

  it("never coerces a null quote acceptance rate to 0%", async () => {
    mockApiResponses(makeSnapshot({ quote_acceptance_rate_percent: null }), makeTrendSnapshot());
    renderWithProviders(<AnalyticsPage />);

    await waitFor(() => expect(screen.getAllByText("Not enough data yet").length).toBeGreaterThan(0));
  });

  it("renders a graceful all-zero snapshot for an organization with no data yet", async () => {
    mockApiResponses(
      makeSnapshot({
        invoice_counts: { total: 0, pending: 0, paid: 0, overdue: 0 },
        revenue_by_currency: {},
        revenue_breakdown: [],
        average_invoice_value: {},
        customer_growth: 0,
        customer_retention: { total_invoiced_customers: 0, repeat_customers: 0, retention_rate_percent: null },
        quote_acceptance_rate_percent: null,
        average_payment_time: { available: false, average_days: null, reason: "no data" },
      }),
      makeTrendSnapshot({
        revenue_trend: {},
        invoice_count_trend: {
          current: "0.00",
          previous: "0.00",
          absolute_difference: "0.00",
          percentage_difference: null,
          direction: "unknown",
        },
        revenue_series: [],
        revenue_forecast: {},
      })
    );
    renderWithProviders(<AnalyticsPage />);

    await waitFor(() => expect(screen.getByText("No revenue yet")).toBeInTheDocument());
    expect(screen.getAllByText("0").length).toBeGreaterThan(0);
  });

  it("shows a translated, generic error message on a failure -- never raw backend text", async () => {
    apiFetchMock.mockRejectedValue(new ApiError("Request failed (500)", 500, { detail: "boom" }));
    renderWithProviders(<AnalyticsPage />);

    await waitFor(() => expect(screen.getAllByRole("alert").length).toBeGreaterThan(0));
    for (const alert of screen.getAllByRole("alert")) {
      expect(alert).toHaveTextContent("Failed to load analytics");
    }
    expect(screen.queryByText("boom")).not.toBeInTheDocument();
  });

  it("shows a permission-denied message on a 403, not raw backend text", async () => {
    apiFetchMock.mockRejectedValue(
      new ApiError("Request failed (403)", 403, { detail: { code: "forbidden" } })
    );
    renderWithProviders(<AnalyticsPage />);

    await waitFor(() => expect(screen.getAllByRole("alert").length).toBeGreaterThan(0));
    for (const alert of screen.getAllByRole("alert")) {
      expect(alert).toHaveTextContent("You don't have permission to view analytics for this organization.");
    }
  });

  it("shows loading skeletons without unmounting the page shell", async () => {
    let resolveFetch: (value: KpiSnapshot) => void = () => {};
    apiFetchMock.mockImplementation((path: unknown) => {
      if (typeof path === "string" && path.includes("/analytics/trends")) {
        return Promise.resolve(makeTrendSnapshot());
      }
      return new Promise<KpiSnapshot>((resolve) => {
        resolveFetch = resolve;
      });
    });
    renderWithProviders(<AnalyticsPage />);

    // The page shell (heading, window selector) is present immediately,
    // even before the first response arrives.
    expect(screen.getByRole("heading", { name: "Analytics" })).toBeInTheDocument();
    expect(screen.getByLabelText("Time period")).toBeInTheDocument();

    resolveFetch(makeSnapshot());
    await waitFor(() => expect(screen.getByText("Total invoices")).toBeInTheDocument());
    const totalInvoicesCard = screen.getByText("Total invoices").closest("article")!;
    expect(within(totalInvoicesCard).getByText("3")).toBeInTheDocument();
  });
});

describe("AnalyticsPage trend engine (Phase 16C)", () => {
  it("renders period comparison cards with current/previous/direction, never only a percentage", async () => {
    mockApiResponses(makeSnapshot(), makeTrendSnapshot());
    renderWithProviders(<AnalyticsPage />);

    await waitFor(() => expect(screen.getAllByText("Revenue (USD)").length).toBeGreaterThan(0));
    // "Revenue (USD)" is also the Monthly Evolution chart's title (same
    // translation key content) -- the comparison card is the first one
    // in DOM order (Period comparison section renders before Monthly
    // evolution), and is the only one wrapped in an <h3> (charts use <h2>).
    const revenueCardTitle = screen
      .getAllByText("Revenue (USD)")
      .find((el) => el.tagName === "H3")!;
    const revenueCard = revenueCardTitle.closest("article")!;
    expect(within(revenueCard).getByText(/200[.,]00/)).toBeInTheDocument();
    expect(within(revenueCard).getByText(/vs\..*100[.,]00.*previously/)).toBeInTheDocument();
    // The arrow/percentage badge renders as multiple text nodes ("▲ ",
    // "100.0", "%"), so check the badge's combined textContent instead of
    // an exact getByText match.
    expect(revenueCard.textContent).toContain("100.0%");
  });

  it("reads the initial comparison from the URL and refetches trends when it changes", async () => {
    currentSearch = "comparison=current_quarter";
    mockApiResponses(makeSnapshot(), makeTrendSnapshot({ comparison_kind: "current_quarter" }));
    renderWithProviders(<AnalyticsPage />);

    await waitFor(() =>
      expect(
        apiFetchMock.mock.calls.some((c) => String(c[0]).includes("comparison=current_quarter"))
      ).toBe(true)
    );

    apiFetchMock.mockClear();
    mockApiResponses(makeSnapshot(), makeTrendSnapshot({ comparison_kind: "current_year" }));
    const select = screen.getByLabelText("Comparison period") as HTMLSelectElement;
    select.value = "current_year";
    select.dispatchEvent(new Event("change", { bubbles: true }));

    await waitFor(() =>
      expect(
        apiFetchMock.mock.calls.some((c) => String(c[0]).includes("comparison=current_year"))
      ).toBe(true)
    );
    expect(routerReplace).toHaveBeenCalledWith(expect.stringContaining("comparison=current_year"));
  });

  it("never combines revenue trend/series/forecast across currencies", async () => {
    mockApiResponses(
      makeSnapshot({ revenue_by_currency: { USD: "222.00", EUR: "111.00" } }),
      makeTrendSnapshot({
        revenue_trend: {
          USD: {
            current: "222.00",
            previous: "111.00",
            absolute_difference: "111.00",
            percentage_difference: "100.00",
            direction: "up",
          },
          EUR: {
            current: "50.00",
            previous: "100.00",
            absolute_difference: "-50.00",
            percentage_difference: "-50.00",
            direction: "down",
          },
        },
        revenue_forecast: {
          USD: {
            available: true,
            method: "simple_moving_average",
            forecast_value: "300.00",
            inputs: ["222.00"],
            window_size: 1,
            reason: null,
          },
          EUR: {
            available: true,
            method: "simple_moving_average",
            forecast_value: "75.00",
            inputs: ["50.00"],
            window_size: 1,
            reason: null,
          },
        },
      })
    );
    renderWithProviders(<AnalyticsPage />);

    await waitFor(() => expect(screen.getAllByText("Revenue (USD)").length).toBeGreaterThan(0));
    expect(screen.getAllByText("Revenue (EUR)").length).toBeGreaterThan(0);
    // No row/card anywhere sums 222+50=272 or 111+100=211 across currencies.
    expect(screen.queryByText(/272[.,]00/)).not.toBeInTheDocument();
    expect(screen.queryByText(/211[.,]00/)).not.toBeInTheDocument();
  });

  it("shows an honest unavailable state for a forecast with fewer than 2 historical periods", async () => {
    mockApiResponses(
      makeSnapshot(),
      makeTrendSnapshot({
        invoice_count_forecast: {
          available: false,
          method: null,
          forecast_value: null,
          inputs: ["1.00"],
          window_size: null,
          reason: "At least 2 historical periods are required to compute a forecast.",
        },
      })
    );
    renderWithProviders(<AnalyticsPage />);

    await waitFor(() =>
      expect(screen.getByText("Not enough history yet to forecast")).toBeInTheDocument()
    );
    expect(screen.queryByText(/historical periods are required/)).not.toBeInTheDocument();
  });

  it("shows the forecast method and period count when available", async () => {
    mockApiResponses(makeSnapshot(), makeTrendSnapshot());
    renderWithProviders(<AnalyticsPage />);

    // formatMoney (lib/money.ts) renders via toLocaleString, so the exact
    // decimal separator is environment-dependent.
    await waitFor(() => expect(screen.getByText(/^150[.,]00$/)).toBeInTheDocument());
    expect(
      screen.getByText("Based on a simple moving average, over the last 2 periods")
    ).toBeInTheDocument();
    expect(screen.getByText("5")).toBeInTheDocument();
    expect(screen.getByText("Based on a linear trend, over the last 2 periods")).toBeInTheDocument();
  });

  it("renders the monthly evolution charts without unmounting on trend loading", async () => {
    mockApiResponses(makeSnapshot(), makeTrendSnapshot());
    renderWithProviders(<AnalyticsPage />);

    await waitFor(() => expect(screen.getByText("Monthly evolution")).toBeInTheDocument());
    expect(screen.getByText("Forecast")).toBeInTheDocument();
    expect(screen.getByText("Period comparison")).toBeInTheDocument();
  });
});
