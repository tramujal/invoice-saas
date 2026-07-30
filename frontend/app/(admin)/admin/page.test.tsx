import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  PlatformBusinessMetrics,
  PlatformDashboard,
  PlatformGrowthMetrics,
  PlatformSystemHealth,
  PlatformUsageMetrics,
} from "@/lib/types";
import { renderWithProviders, screen, waitFor } from "@/tests/test-utils";

import PlatformAdminDashboardPage from "./page";

vi.mock("next/navigation", () => ({
  usePathname: () => "/admin",
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}));

const apiFetchMock = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    apiFetch: (...args: unknown[]) => apiFetchMock(...args),
  };
});

const overview: PlatformDashboard = {
  organizations_total: 5,
  organizations_new_7d: 1,
  organizations_new_30d: 2,
  users_total: 8,
  users_new_7d: 1,
  users_new_30d: 3,
  invoices_total: 20,
  quotes_total: 10,
  customers_total: 15,
  products_total: 7,
  reminder_emails_sent_7d: 4,
  reminder_emails_failed_7d: 0,
  ai_actions_executed_7d: 6,
  health: {
    database_reachable: true,
    email_provider_configured: true,
    email_provider: "resend",
    ai_provider_configured: true,
    ai_provider: "anthropic",
    reminder_emails_pending: 0,
    reminder_emails_sent_7d: 4,
    reminder_emails_failed_7d: 0,
    queue_pending: 0,
    queue_running: 0,
    queue_retry_scheduled: 0,
    jobs_failed_total: 0,
    jobs_succeeded_total: 10,
    storage_used_mb: 0,
    database_size_mb: 1.2,
    average_api_latency_ms: 15,
    error_rate_percent: 0,
    request_sample_count: 100,
  },
};

const business: PlatformBusinessMetrics = {
  organizations_total: 5,
  active_users_total: 8,
  paying_organizations: 2,
  trial_organizations: 1,
  mrr: "58.00",
  arr: "696.00",
  currency: "USD",
  churn_rate_30d: 0,
  conversion_rate_30d: 50,
  average_revenue_per_organization: "29.00",
};

const usage: PlatformUsageMetrics = {
  ai_requests_30d: 12,
  api_keys_active: 3,
  api_keys_used_7d: 1,
  webhook_deliveries_30d: 4,
  webhook_deliveries_succeeded_30d: 3,
  webhook_deliveries_failed_30d: 1,
  background_jobs_30d: 20,
  background_jobs_succeeded_30d: 18,
  background_jobs_failed_30d: 2,
  emails_sent_30d: 9,
  notifications_created_30d: 14,
};

const growth: PlatformGrowthMetrics = {
  daily_signups: [{ day: "2026-07-28", count: 2 }],
  weekly_active_organizations: [{ week_start: "2026-07-27", count: 3 }],
  monthly_growth_percent: 12.5,
  feature_adoption: [
    { feature: "ai_enabled", adopted_paying_organizations: 1, adopted_percent: 50 },
  ],
};

const health: PlatformSystemHealth = overview.health;

function mockAllEndpoints() {
  apiFetchMock.mockImplementation((path: string) => {
    if (path.startsWith("/admin/dashboard/business")) return Promise.resolve(business);
    if (path.startsWith("/admin/dashboard/usage")) return Promise.resolve(usage);
    if (path.startsWith("/admin/dashboard/growth")) return Promise.resolve(growth);
    if (path.startsWith("/admin/system/health")) return Promise.resolve(health);
    if (path.startsWith("/admin/dashboard")) return Promise.resolve(overview);
    return Promise.reject(new Error(`unexpected call: ${path}`));
  });
}

beforeEach(() => {
  apiFetchMock.mockReset();
});

describe("PlatformAdminDashboardPage", () => {
  it("renders business, usage, health, and growth sections with real data", async () => {
    mockAllEndpoints();
    renderWithProviders(<PlatformAdminDashboardPage />);

    expect(await screen.findByText("Business Metrics")).toBeInTheDocument();
    expect(screen.getByText("Usage Metrics")).toBeInTheDocument();
    expect(screen.getByText("Growth")).toBeInTheDocument();

    await waitFor(() => expect(screen.getByText(/USD 58[.,]00/)).toBeInTheDocument());
    expect(screen.getByText(/USD 696[.,]00/)).toBeInTheDocument();
    expect(screen.getByText("50%")).toBeInTheDocument(); // conversion rate
  });

  it("shows an error banner for one section without blanking the others", async () => {
    apiFetchMock.mockImplementation((path: string) => {
      if (path.startsWith("/admin/dashboard/business")) return Promise.reject(new Error("boom"));
      if (path.startsWith("/admin/dashboard/usage")) return Promise.resolve(usage);
      if (path.startsWith("/admin/dashboard/growth")) return Promise.resolve(growth);
      if (path.startsWith("/admin/system/health")) return Promise.resolve(health);
      if (path.startsWith("/admin/dashboard")) return Promise.resolve(overview);
      return Promise.reject(new Error(`unexpected call: ${path}`));
    });

    renderWithProviders(<PlatformAdminDashboardPage />);

    await waitFor(() =>
      expect(screen.getByText("Failed to load this section. Please try again.")).toBeInTheDocument()
    );
    // Usage section still rendered its real data despite Business failing.
    await waitFor(() => expect(screen.getByText("12")).toBeInTheDocument());
  });

  it("shows loading skeletons before data arrives", () => {
    apiFetchMock.mockImplementation(() => new Promise(() => {})); // never resolves
    const { container } = renderWithProviders(<PlatformAdminDashboardPage />);

    expect(screen.getByText("Business Metrics")).toBeInTheDocument();
    expect(screen.queryByText(/USD/)).not.toBeInTheDocument();
    expect(container.querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);
  });

  it("renders growth chart data and feature adoption", async () => {
    mockAllEndpoints();
    renderWithProviders(<PlatformAdminDashboardPage />);

    await waitFor(() => expect(screen.getByText("12.5%")).toBeInTheDocument());
    expect(await screen.findByText("Feature adoption (paying organizations)")).toBeInTheDocument();
  });
});
