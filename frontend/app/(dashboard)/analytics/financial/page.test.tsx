import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { setAuthSession } from "@/lib/auth-storage";
import type {
  AnomaliesResponse,
  CashflowCalendarResponse,
  CollectionsForecastResponse,
  CustomersSectionResponse,
  ExecutiveOverviewResponse,
  FinancialAnalysisPayload,
  FinancialMetricValue,
  ForecastAccuracyResponse,
  ForecastMethodsResponse,
  ForecastSummaryResponse,
  InsightReportResponse,
  MonthlyProjectionResponse,
  ProductsSectionResponse,
  QuotesSectionResponse,
  ReceivablesAgingResponse,
  RevenueForecastResponse,
  RevenueTrendsResponse,
  ScenarioResponse,
} from "@/lib/types";
import { renderWithProviders, screen, waitFor } from "@/tests/test-utils";

import FinancialDashboardPage from "./page";

const apiFetchMock = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    apiFetch: (...args: unknown[]) => apiFetchMock(...args),
  };
});

function metric(overrides: Partial<FinancialMetricValue> = {}): FinancialMetricValue {
  return {
    id: "m",
    label: "Metric",
    value: "1000.00",
    currency_code: "USD",
    period: "current_month",
    comparison_period: "previous_month",
    previous_value: "500.00",
    percent_change: "100.00",
    trend_direction: "up",
    data_completeness: "complete",
    formula_key: "x",
    note: null,
    ...overrides,
  };
}

function emptyMetric(overrides: Partial<FinancialMetricValue> = {}): FinancialMetricValue {
  return metric({
    value: null,
    previous_value: null,
    percent_change: null,
    trend_direction: null,
    data_completeness: "insufficient",
    ...overrides,
  });
}

function makeOverview(overrides: Partial<ExecutiveOverviewResponse> = {}): ExecutiveOverviewResponse {
  return {
    generated_at: "2026-03-15T00:00:00Z",
    period_start: "2026-03-01",
    period_end: "2026-04-01",
    by_currency: [
      {
        currency_code: "USD",
        invoiced_this_month: metric({ id: "invoiced_this_month", label: "Revenue this month" }),
        collected_this_month: metric({ id: "collected_this_month", label: "Collected revenue this month" }),
        outstanding_receivables: metric({ id: "outstanding_receivables", label: "Outstanding receivables" }),
        overdue_receivables: metric({ id: "overdue_receivables", label: "Overdue receivables" }),
        expected_collections_next_30_days: metric({
          id: "expected_collections_next_30_days",
          label: "Expected collections, next 30 days",
          trend_direction: null,
          percent_change: null,
          previous_value: null,
        }),
        average_invoice_value: metric({ id: "average_invoice_value", label: "Average invoice value" }),
        collection_rate: metric({ id: "collection_rate", label: "Collection rate", value: "33.33" }),
        overdue_rate: metric({ id: "overdue_rate", label: "Overdue rate", value: "10.00" }),
      },
    ],
    quote_conversion_rate: metric({ id: "quote_conversion_rate", label: "Quote conversion rate", value: "50.00" }),
    average_days_to_payment: metric({ id: "average_days_to_payment", label: "Average days to payment", value: "4.2" }),
    capabilities: {
      advanced_financial_analytics_enabled: true,
      revenue_forecasting_enabled: false,
      ai_financial_recommendations_enabled: false,
      remaining_financial_ai_reports_this_month: null,
    },
    ...overrides,
  };
}

const EMPTY_OVERVIEW: ExecutiveOverviewResponse = {
  generated_at: "2026-03-15T00:00:00Z",
  period_start: "2026-03-01",
  period_end: "2026-04-01",
  by_currency: [],
  quote_conversion_rate: emptyMetric({ id: "quote_conversion_rate", label: "Quote conversion rate" }),
  average_days_to_payment: emptyMetric({ id: "average_days_to_payment", label: "Average days to payment" }),
  capabilities: {
    advanced_financial_analytics_enabled: true,
    revenue_forecasting_enabled: false,
    ai_financial_recommendations_enabled: false,
    remaining_financial_ai_reports_this_month: null,
  },
};

const EMPTY_TRENDS: RevenueTrendsResponse = {
  generated_at: "2026-03-15T00:00:00Z",
  granularity: "monthly",
  points: [],
  month_over_month_change_percent: {},
  year_over_year_change_percent: {},
  rolling_3_month_average: {},
  rolling_6_month_average: {},
  data_completeness: "insufficient",
};

const EMPTY_AGING: ReceivablesAgingResponse = {
  generated_at: "2026-03-15T00:00:00Z",
  as_of_date: "2026-03-15",
  buckets: [],
  top_overdue_customers: [],
  invoices_missing_due_date: 0,
};

const EMPTY_CUSTOMERS: CustomersSectionResponse = {
  generated_at: "2026-03-15T00:00:00Z",
  period_start: "2026-03-01",
  period_end: "2026-04-01",
  top_by_revenue: [],
  top_by_outstanding: [],
  most_overdue: [],
  concentration: [],
  repeat_contribution: [],
  customer_growth_count: 0,
  at_risk: [],
};

const EMPTY_PRODUCTS: ProductsSectionResponse = {
  generated_at: "2026-03-15T00:00:00Z",
  period_start: "2026-03-01",
  period_end: "2026-04-01",
  by_revenue: [],
  trends: [],
  concentration: [],
  declining: [],
};

const EMPTY_QUOTES: QuotesSectionResponse = {
  generated_at: "2026-03-15T00:00:00Z",
  counts: { created: 0, sent: 0, accepted: 0, rejected: 0, expired: 0, converted: 0 },
  conversion_rate_percent: null,
  average_time_to_acceptance_days: emptyMetric({ id: "average_time_to_acceptance_days", label: "x" }),
  by_currency: [],
};

const EMPTY_CALENDAR: CashflowCalendarResponse = {
  generated_at: "2026-03-15T00:00:00Z",
  as_of_date: "2026-03-15",
  granularity: "week",
  horizon_days: 30,
  points: [],
  disclaimer: "This is a receivables forecast, not a profit-and-loss statement.",
};

// Phase 24.2 -- deterministic revenue forecasting defaults (a brand-new
// organization: no plan restriction, simply nothing to forecast yet).
const EMPTY_REVENUE_FORECAST: RevenueForecastResponse = {
  generated_at: "2026-03-15T00:00:00Z",
  plan_restricted: false,
  results: [],
};

const EMPTY_COLLECTIONS_FORECAST: CollectionsForecastResponse = {
  generated_at: "2026-03-15T00:00:00Z",
  plan_restricted: false,
  results: [],
};

const EMPTY_MONTHLY_PROJECTION: MonthlyProjectionResponse = {
  generated_at: "2026-03-15T00:00:00Z",
  plan_restricted: false,
  months: 6,
  points: [],
};

const EMPTY_FORECAST_SUMMARY: ForecastSummaryResponse = {
  generated_at: "2026-03-15T00:00:00Z",
  plan_restricted: false,
  results: [],
};

const EMPTY_FORECAST_ACCURACY: ForecastAccuracyResponse = {
  generated_at: "2026-03-15T00:00:00Z",
  plan_restricted: false,
  results: [],
};

const EMPTY_FORECAST_METHODS: ForecastMethodsResponse = {
  generated_at: "2026-03-15T00:00:00Z",
  plan_restricted: false,
  methods: [
    { method: "seasonal_naive", minimum_observations_required: 14 },
    { method: "rolling_average", minimum_observations_required: 3 },
    { method: "weighted_moving_average", minimum_observations_required: 3 },
    { method: "linear_trend", minimum_observations_required: 3 },
  ],
};

const EMPTY_ANOMALIES: AnomaliesResponse = {
  generated_at: "2026-03-15T00:00:00Z",
  plan_restricted: false,
  flags: [],
};

// Phase 24.3 -- the AI Financial Advisor.
function analysis(overrides: Partial<FinancialAnalysisPayload> = {}): FinancialAnalysisPayload {
  return {
    executive_summary: "Revenue is stable with modest growth this month.",
    overall_health: "good",
    confidence_notice: "Based on limited history; confidence is currently low.",
    observations: [
      {
        category: "revenue",
        severity: "info",
        title: "Revenue grew slightly",
        explanation: "Invoiced revenue increased compared to the prior month.",
        evidence: [{ label: "Revenue this month", value: "USD 1200.00" }],
      },
    ],
    recommendations: [
      {
        priority: "medium",
        title: "Follow up on overdue invoices",
        action: "Reach out to customers with invoices more than 30 days overdue.",
        reason: "Overdue receivables represent 10% of outstanding balances this month.",
        expected_impact: "Improved collection rate next month.",
        limitations: "Based on a small sample of overdue invoices; confidence is low.",
      },
    ],
    forecast_commentary: "Not enough history yet for a reliable forecast.",
    strengths: ["Consistent monthly invoicing."],
    risks: ["High dependency on a single customer."],
    opportunities: ["Convert more sent quotes."],
    next_actions: ["Review overdue invoices this week."],
    disclaimer: "This analysis is generated from deterministic metrics and is not financial, tax, or legal advice.",
    ...overrides,
  };
}

function insightReport(overrides: Partial<InsightReportResponse> = {}): InsightReportResponse {
  return {
    id: "report-1",
    status: "completed",
    period_start: "2026-03-01",
    period_end: "2026-04-01",
    ai_provider: "anthropic",
    ai_model: "claude-sonnet-5",
    generated_at: "2026-03-15T00:00:00Z",
    expires_at: "2026-03-16T00:00:00Z",
    error_code: null,
    error_message: null,
    created_by_user_id: "user-1",
    created_at: "2026-03-15T00:00:00Z",
    analysis: analysis(),
    reused: false,
    ...overrides,
  };
}

const EMPTY_SCENARIO: ScenarioResponse = {
  generated_at: "2026-03-15T00:00:00Z",
  plan_restricted: false,
  scenario: "base",
  assumptions_used: { invoice_growth_percent: "0", collection_delay_days: 0, quote_conversion_delta_percent: "0" },
  results: [],
};

function mockAllEndpoints(
  overview: ExecutiveOverviewResponse | (() => Promise<never>),
  forecastOverrides: {
    revenue?: RevenueForecastResponse;
    collections?: CollectionsForecastResponse;
    monthlyProjection?: MonthlyProjectionResponse;
    summary?: ForecastSummaryResponse;
    accuracy?: ForecastAccuracyResponse;
    methods?: ForecastMethodsResponse;
    anomalies?: AnomaliesResponse;
    scenario?: ScenarioResponse;
  } = {},
  aiOverrides: {
    latest?: InsightReportResponse | null | (() => Promise<never>);
    generate?: (body: unknown) => Promise<InsightReportResponse>;
  } = {}
) {
  apiFetchMock.mockImplementation((path: string, init?: RequestInit) => {
    if (path.endsWith("/financial-intelligence/overview")) {
      return typeof overview === "function" ? overview() : Promise.resolve(overview);
    }
    if (path.endsWith("/financial-intelligence/revenue-trends")) return Promise.resolve(EMPTY_TRENDS);
    if (path.endsWith("/financial-intelligence/receivables-aging")) return Promise.resolve(EMPTY_AGING);
    if (path.endsWith("/financial-intelligence/customers")) return Promise.resolve(EMPTY_CUSTOMERS);
    if (path.endsWith("/financial-intelligence/products")) return Promise.resolve(EMPTY_PRODUCTS);
    if (path.endsWith("/financial-intelligence/quotes")) return Promise.resolve(EMPTY_QUOTES);
    if (path.includes("/financial-intelligence/cashflow-calendar")) return Promise.resolve(EMPTY_CALENDAR);
    if (path.endsWith("/financial-intelligence/forecast/revenue"))
      return Promise.resolve(forecastOverrides.revenue ?? EMPTY_REVENUE_FORECAST);
    if (path.endsWith("/financial-intelligence/forecast/collections"))
      return Promise.resolve(forecastOverrides.collections ?? EMPTY_COLLECTIONS_FORECAST);
    if (path.includes("/financial-intelligence/forecast/monthly-projection"))
      return Promise.resolve(forecastOverrides.monthlyProjection ?? EMPTY_MONTHLY_PROJECTION);
    if (path.endsWith("/financial-intelligence/forecast/summary"))
      return Promise.resolve(forecastOverrides.summary ?? EMPTY_FORECAST_SUMMARY);
    if (path.endsWith("/financial-intelligence/forecast/accuracy"))
      return Promise.resolve(forecastOverrides.accuracy ?? EMPTY_FORECAST_ACCURACY);
    if (path.endsWith("/financial-intelligence/forecast/methods"))
      return Promise.resolve(forecastOverrides.methods ?? EMPTY_FORECAST_METHODS);
    if (path.endsWith("/financial-intelligence/forecast/anomalies"))
      return Promise.resolve(forecastOverrides.anomalies ?? EMPTY_ANOMALIES);
    if (path.endsWith("/financial-intelligence/forecast/scenario"))
      return Promise.resolve(forecastOverrides.scenario ?? EMPTY_SCENARIO);
    if (path.endsWith("/financial-intelligence/insights/latest")) {
      const latest = aiOverrides.latest;
      if (typeof latest === "function") return latest();
      return Promise.resolve(latest === undefined ? null : latest);
    }
    if (path.endsWith("/financial-intelligence/insights/generate") && init?.method === "POST") {
      if (aiOverrides.generate) return aiOverrides.generate(JSON.parse((init.body as string) ?? "{}"));
      return Promise.resolve(insightReport({ status: "pending", analysis: null }));
    }
    return Promise.reject(new Error(`unexpected call: ${path}`));
  });
}

beforeEach(() => {
  window.localStorage.clear();
  apiFetchMock.mockReset();
  setAuthSession({
    token: "test-token",
    apiBaseUrl: "http://localhost:8000",
    organizationId: "org-1",
    userEmail: "self@example.com",
  });
});

describe("FinancialDashboardPage", () => {
  it("shows the plan-restricted empty state on a 403 feature_not_available", async () => {
    mockAllEndpoints(() =>
      Promise.reject(
        new ApiError("Request failed (403)", 403, {
          detail: {
            code: "feature_not_available",
            feature: "advanced_financial_analytics",
            plan: { id: "plan-1", code: "free", name: "Free" },
            message: "Advanced Financial Analytics is not included in your Free plan.",
          },
        })
      )
    );

    renderWithProviders(<FinancialDashboardPage />);

    expect(await screen.findByText("Not included in your plan")).toBeInTheDocument();
    expect(screen.getByText(/Free plan/)).toBeInTheDocument();
    // The 6 other sections must never even be requested once the gate denies.
    await new Promise((r) => setTimeout(r, 20));
    expect(apiFetchMock).not.toHaveBeenCalledWith(
      expect.stringContaining("revenue-trends"),
      expect.anything()
    );
  });

  it("renders the 8 KPI cards with real values for a single-currency organization", async () => {
    mockAllEndpoints(makeOverview());
    renderWithProviders(<FinancialDashboardPage />);

    await waitFor(() => expect(screen.getByText("Revenue this month")).toBeInTheDocument());
    expect(screen.getByText("Collected this month")).toBeInTheDocument();
    expect(screen.getByText("Outstanding receivables")).toBeInTheDocument();
    expect(screen.getByText("Overdue receivables")).toBeInTheDocument();
    expect(screen.getByText("Expected collections (30 days)")).toBeInTheDocument();
    expect(screen.getByText("Average invoice value")).toBeInTheDocument();
    expect(screen.getByText("Collection rate")).toBeInTheDocument();
    expect(screen.getByText("Quote conversion rate")).toBeInTheDocument();

    // Only ONE currency block -- no per-currency heading shown.
    expect(screen.queryByRole("heading", { name: "USD" })).not.toBeInTheDocument();
  });

  it("groups KPIs per currency when the organization has more than one", async () => {
    const overview = makeOverview();
    const eurRow = { ...overview.by_currency[0], currency_code: "EUR" };
    overview.by_currency = [overview.by_currency[0], eurRow];
    mockAllEndpoints(overview);

    renderWithProviders(<FinancialDashboardPage />);

    await waitFor(() => expect(screen.getAllByText("Revenue this month")).toHaveLength(2));
    expect(screen.getByText("USD")).toBeInTheDocument();
    expect(screen.getByText("EUR")).toBeInTheDocument();
  });

  it("shows empty states for every section on a brand-new organization", async () => {
    mockAllEndpoints(EMPTY_OVERVIEW);
    renderWithProviders(<FinancialDashboardPage />);

    await waitFor(() => expect(screen.getByText("No open receivables")).toBeInTheDocument());
    expect(await screen.findByText("No customer revenue yet")).toBeInTheDocument();
    expect(await screen.findByText("No product revenue yet")).toBeInTheDocument();
    expect(await screen.findByText("Nothing expected in this window")).toBeInTheDocument();
    // Quote conversion rate has no data -> "No prior period" caption, not a trend badge.
    expect(screen.getAllByText("No prior period").length).toBeGreaterThan(0);
  });

  it("shows loading skeletons before data arrives", () => {
    let resolveOverview: (value: ExecutiveOverviewResponse) => void = () => {};
    apiFetchMock.mockImplementation((path: string) => {
      if (path.endsWith("/financial-intelligence/overview")) {
        return new Promise((resolve) => {
          resolveOverview = resolve;
        });
      }
      return Promise.resolve(EMPTY_TRENDS);
    });

    renderWithProviders(<FinancialDashboardPage />);
    expect(screen.getByText("Financial Dashboard")).toBeInTheDocument();
    // Titles render immediately (translated by the caller, independent of
    // fetch state); only the VALUE waits for real data -- no crash while
    // overview is still null.
    expect(screen.getByText("Revenue this month")).toBeInTheDocument();
    expect(screen.queryByText(/USD/)).not.toBeInTheDocument();
    resolveOverview(EMPTY_OVERVIEW);
  });

  it("shows the deterministic-only badge", async () => {
    mockAllEndpoints(makeOverview());
    renderWithProviders(<FinancialDashboardPage />);

    await waitFor(() => expect(screen.getByText("Revenue this month")).toBeInTheDocument());
    expect(screen.getByText("No AI · No estimates")).toBeInTheDocument();
  });

  // --- Phase 24.2 -- deterministic revenue forecasting --------------------

  it("renders the revenue forecast chart and horizon cards when a model is selected", async () => {
    mockAllEndpoints(makeOverview(), {
      revenue: {
        generated_at: "2026-03-15T00:00:00Z",
        plan_restricted: false,
        results: [
          {
            currency_code: "USD",
            status: "ok",
            model: "linear_trend",
            sample_size: 14,
            confidence: "high",
            minimum_observations_required: 2,
            horizons: [
              { horizon_days: 30, forecast_value: "1000.00", lower_bound: "900.00", upper_bound: "1100.00" },
              { horizon_days: 90, forecast_value: "3000.00", lower_bound: "2700.00", upper_bound: "3300.00" },
              { horizon_days: 180, forecast_value: "6000.00", lower_bound: "5400.00", upper_bound: "6600.00" },
              { horizon_days: 365, forecast_value: "12000.00", lower_bound: "10000.00", upper_bound: "14000.00" },
            ],
          },
        ],
      },
    });

    renderWithProviders(<FinancialDashboardPage />);

    await waitFor(() => expect(screen.getByText("Revenue forecast")).toBeInTheDocument());
    expect((await screen.findAllByText("Linear trend")).length).toBeGreaterThan(0);
    expect(screen.getByText("High confidence")).toBeInTheDocument();
    expect(screen.getByText("30 days")).toBeInTheDocument();
    expect(screen.getByText("365 days")).toBeInTheDocument();
  });

  it("shows an insufficient-data state for a currency with too little history", async () => {
    mockAllEndpoints(makeOverview(), {
      revenue: {
        generated_at: "2026-03-15T00:00:00Z",
        plan_restricted: false,
        results: [
          {
            currency_code: "USD",
            status: "insufficient_data",
            model: null,
            sample_size: 1,
            confidence: "insufficient_data",
            minimum_observations_required: 2,
            horizons: [],
          },
        ],
      },
    });

    renderWithProviders(<FinancialDashboardPage />);

    await waitFor(() => expect(screen.getByText("Revenue forecast")).toBeInTheDocument());
    expect(await screen.findByText(/only 1 on file/)).toBeInTheDocument();
  });

  it("shows the plan-restricted state for forecast sections when the plan lacks forecasting", async () => {
    mockAllEndpoints(makeOverview(), {
      revenue: { generated_at: "2026-03-15T00:00:00Z", plan_restricted: true, results: [] },
      collections: { generated_at: "2026-03-15T00:00:00Z", plan_restricted: true, results: [] },
      summary: { generated_at: "2026-03-15T00:00:00Z", plan_restricted: true, results: [] },
      scenario: {
        generated_at: "2026-03-15T00:00:00Z",
        plan_restricted: true,
        scenario: "base",
        assumptions_used: { invoice_growth_percent: "0", collection_delay_days: 0, quote_conversion_delta_percent: "0" },
        results: [],
      },
    });

    renderWithProviders(<FinancialDashboardPage />);

    // 4 independent sections each render this exact string once their OWN
    // plan_restricted state resolves (Revenue Forecast, Expected
    // Collections, Forecast Confidence, and the AI Advisor) -- waiting for
    // all 4 (not just the first, which can resolve before the others)
    // avoids a race where this assertion runs before revenueForecast's own
    // fetch (and therefore forecastPlanRestricted) has resolved.
    await waitFor(() => expect(screen.getAllByText("Not included in your plan").length).toBeGreaterThanOrEqual(4));
    // Sections gated purely by `planRestricted` (no separate empty-state
    // text of their own) render nothing rather than a stray heading --
    // Model Explanation is one of these.
    expect(screen.queryByText("How this forecast is calculated")).not.toBeInTheDocument();
  });

  it("renders anomaly flags with their evidence text", async () => {
    mockAllEndpoints(makeOverview(), {
      anomalies: {
        generated_at: "2026-03-15T00:00:00Z",
        plan_restricted: false,
        flags: [
          {
            rule: "revenue_drop",
            severity: "high",
            currency_code: "USD",
            sample_size: 6,
            evidence: "Invoiced revenue fell 80% month-over-month (1000 -> 200 USD).",
          },
        ],
      },
    });

    renderWithProviders(<FinancialDashboardPage />);

    await waitFor(() => expect(screen.getByText(/Revenue drop/)).toBeInTheDocument());
    expect(screen.getByText(/Invoiced revenue fell 80%/)).toBeInTheDocument();
    expect(screen.getByText("High")).toBeInTheDocument();
  });

  it("re-posts the scenario evaluation when an assumption input changes", async () => {
    const { fireEvent } = await import("@testing-library/react");
    mockAllEndpoints(makeOverview());
    renderWithProviders(<FinancialDashboardPage />);

    await waitFor(() => expect(screen.getByText("Scenario controls")).toBeInTheDocument());
    apiFetchMock.mockClear();

    const optimisticButton = screen.getByRole("button", { name: "Optimistic" });
    fireEvent.click(optimisticButton);

    await waitFor(
      () => {
        const scenarioCall = apiFetchMock.mock.calls.find((call: unknown[]) =>
          (call[0] as string).endsWith("/financial-intelligence/forecast/scenario")
        );
        expect(scenarioCall).toBeDefined();
        const body = JSON.parse((scenarioCall![1] as RequestInit).body as string);
        expect(body.scenario).toBe("optimistic");
        expect(body.assumptions.invoice_growth_percent).toBe(10);
      },
      { timeout: 2000 }
    );
  });

  it("shows a CSV export button once monthly projection data is available", async () => {
    mockAllEndpoints(makeOverview(), {
      monthlyProjection: {
        generated_at: "2026-03-15T00:00:00Z",
        plan_restricted: false,
        months: 1,
        points: [
          {
            month: "2026-04",
            currency_code: "USD",
            expected_value: "1000.00",
            lower_bound: "900.00",
            upper_bound: "1100.00",
            confidence: "medium",
            sample_size: 6,
          },
        ],
      },
    });

    renderWithProviders(<FinancialDashboardPage />);

    expect(await screen.findByRole("button", { name: "Export CSV" })).toBeInTheDocument();
  });

  // --- Phase 24.3 -- the AI Financial Advisor -------------------------

  function overviewWithAiEnabled(overrides: Partial<ExecutiveOverviewResponse> = {}) {
    return makeOverview({
      capabilities: {
        advanced_financial_analytics_enabled: true,
        revenue_forecasting_enabled: false,
        ai_financial_recommendations_enabled: true,
        remaining_financial_ai_reports_this_month: 5,
      },
      ...overrides,
    });
  }

  it("shows the plan-restricted state for the AI advisor when the plan lacks it", async () => {
    mockAllEndpoints(makeOverview()); // default capabilities: ai_financial_recommendations_enabled: false

    renderWithProviders(<FinancialDashboardPage />);

    expect(await screen.findByText("AI Financial Advisor")).toBeInTheDocument();
    // Two independent "Not included in your plan" instances are expected
    // here: the AI advisor itself uses the identical English string as
    // the forecast sections (both plan-restricted by this same mocked
    // overview), so this just proves the advisor's own copy renders.
    expect((await screen.findAllByText("Not included in your plan")).length).toBeGreaterThan(0);
  });

  it("shows an empty state with a Generate button when no report exists yet", async () => {
    mockAllEndpoints(overviewWithAiEnabled(), {}, { latest: null });

    renderWithProviders(<FinancialDashboardPage />);

    expect(await screen.findByText("No analysis yet")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Generate analysis" })).toBeInTheDocument();
  });

  it("shows a pending indicator while a report is being generated", async () => {
    mockAllEndpoints(overviewWithAiEnabled(), {}, {
      latest: insightReport({ status: "pending", analysis: null, generated_at: null, expires_at: null }),
    });

    renderWithProviders(<FinancialDashboardPage />);

    expect(await screen.findByText("Generating your analysis")).toBeInTheDocument();
  });

  it("shows a failed state with a translated, error-code-specific message", async () => {
    mockAllEndpoints(overviewWithAiEnabled(), {}, {
      latest: insightReport({
        status: "failed",
        analysis: null,
        generated_at: null,
        expires_at: null,
        error_code: "provider_timeout",
        error_message: "timed out",
      }),
    });

    renderWithProviders(<FinancialDashboardPage />);

    expect(await screen.findByText("Analysis failed")).toBeInTheDocument();
    expect(screen.getByText("The AI provider took too long to respond. Please try again.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("renders a completed report's full content -- summary, health, observations, recommendations, lists, disclaimer", async () => {
    mockAllEndpoints(overviewWithAiEnabled(), {}, { latest: insightReport() });

    renderWithProviders(<FinancialDashboardPage />);

    expect(await screen.findByText("Revenue is stable with modest growth this month.")).toBeInTheDocument();
    expect(screen.getByText("Good")).toBeInTheDocument(); // overall_health badge
    expect(screen.getByText("Revenue grew slightly")).toBeInTheDocument();
    expect(screen.getByText("Revenue this month:")).toBeInTheDocument();
    expect(screen.getByText("USD 1200.00")).toBeInTheDocument();
    expect(screen.getByText("Follow up on overdue invoices")).toBeInTheDocument();
    expect(screen.getByText("Consistent monthly invoicing.")).toBeInTheDocument(); // strengths
    expect(screen.getByText("High dependency on a single customer.")).toBeInTheDocument(); // risks
    expect(screen.getByText("Convert more sent quotes.")).toBeInTheDocument(); // opportunities
    expect(screen.getByText("Review overdue invoices this week.")).toBeInTheDocument(); // next actions
    expect(
      screen.getByText("This analysis is generated from deterministic metrics and is not financial, tax, or legal advice.")
    ).toBeInTheDocument();
    // Not a reused/cached result -- no cached indicator shown.
    expect(screen.queryByText("Cached result")).not.toBeInTheDocument();
  });

  it("shows a cached-result indicator when the report was reused rather than freshly generated", async () => {
    mockAllEndpoints(overviewWithAiEnabled(), {}, { latest: insightReport({ reused: true }) });

    renderWithProviders(<FinancialDashboardPage />);

    expect(await screen.findByText("Cached result")).toBeInTheDocument();
  });

  it("clicking Generate analysis POSTs force:false and then shows the pending state", async () => {
    const generate = vi.fn((body: unknown) =>
      Promise.resolve(insightReport({ status: "pending", analysis: null, generated_at: null, expires_at: null }))
    );
    mockAllEndpoints(overviewWithAiEnabled(), {}, { latest: null, generate });

    renderWithProviders(<FinancialDashboardPage />);

    const button = await screen.findByRole("button", { name: "Generate analysis" });
    button.click();

    await waitFor(() => expect(screen.getByText("Generating your analysis")).toBeInTheDocument());
    expect(generate).toHaveBeenCalledWith({ force: false });
  });

  it("clicking Refresh analysis on a completed report POSTs force:true", async () => {
    const generate = vi.fn((body: unknown) => Promise.resolve(insightReport({ reused: false })));
    mockAllEndpoints(overviewWithAiEnabled(), {}, { latest: insightReport(), generate });

    renderWithProviders(<FinancialDashboardPage />);

    const button = await screen.findByRole("button", { name: "Refresh analysis" });
    button.click();

    await waitFor(() => expect(generate).toHaveBeenCalledWith({ force: true }));
  });

  it("shows a quota-exceeded message when the monthly AI report limit is reached", async () => {
    const generate = () =>
      Promise.reject(
        new ApiError("Request failed (409)", 409, {
          detail: {
            code: "plan_limit_reached",
            resource: "financial_ai_reports",
            used: 5,
            limit: 5,
            plan: { id: "plan-1", code: "pro", name: "Pro" },
            message: "You've reached your plan's financial ai reports limit (5/5) on the Pro plan.",
          },
        })
      );
    mockAllEndpoints(overviewWithAiEnabled(), {}, { latest: null, generate });

    renderWithProviders(<FinancialDashboardPage />);

    const button = await screen.findByRole("button", { name: "Generate analysis" });
    button.click();

    expect(await screen.findByText("You've used 5/5 AI analyses included in your plan this month.")).toBeInTheDocument();
  });
});
