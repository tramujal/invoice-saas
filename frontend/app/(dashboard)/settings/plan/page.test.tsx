import { beforeEach, describe, expect, it, vi } from "vitest";

import { setAuthSession } from "@/lib/auth-storage";
import type { OrganizationEntitlements, OrganizationUsage, Subscription } from "@/lib/types";
import { renderWithProviders, screen, waitFor } from "@/tests/test-utils";

import PlanAndLimitsPage from "./page";

vi.mock("next/navigation", () => ({
  usePathname: () => "/settings/plan",
}));

const apiFetchMock = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    apiFetch: (...args: unknown[]) => apiFetchMock(...args),
  };
});

const freeEntitlements: OrganizationEntitlements = {
  plan_id: "plan_free",
  plan_code: "free",
  plan_name: "Free",
  limits: {
    max_users: 2,
    max_customers: 100,
    max_products: 100,
    max_invoices_per_month: 50,
    max_quotes_per_month: 50,
    max_ai_actions_per_month: 25,
    storage_limit_mb: 500,
    max_api_keys: 1,
    max_webhooks: 0,
  },
  features: {
    custom_branding_enabled: false,
    api_access_enabled: false,
    advanced_reports_enabled: false,
    analytics_enabled: false,
    forecasting_enabled: false,
    ai_enabled: false,
    background_jobs_enabled: false,
  },
};

const freeUsage: OrganizationUsage = {
  users: { used: 1, limit: 2, unlimited: false },
  customers: { used: 18, limit: 100, unlimited: false },
  products: { used: 4, limit: 100, unlimited: false },
  invoices: { used: 6, limit: 50, unlimited: false },
  quotes: { used: 3, limit: 50, unlimited: false },
  ai_actions: { used: 9, limit: 25, unlimited: false },
  storage: { used: 0, limit: 500, unlimited: false },
};

const activeSubscription: Subscription = {
  id: "sub-1",
  organization_id: "org-1",
  plan: {
    id: "plan_free",
    code: "free",
    name: "Free",
    description: null,
    is_active: true,
    is_default: true,
    sort_order: 0,
    public: true,
    monthly_price: "0.00",
    yearly_price: "0.00",
    currency: "USD",
    limits: freeEntitlements.limits,
    features: freeEntitlements.features,
    version: 1,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  },
  status: "active",
  billing_period: "monthly",
  trial_start: null,
  trial_end: null,
  current_period_start: "2026-01-01T00:00:00Z",
  current_period_end: "2026-02-01T00:00:00Z",
  cancel_at_period_end: false,
  canceled_at: null,
  ended_at: null,
  capabilities: {
    can_use_ai: false,
    can_use_analytics: false,
    can_use_forecasting: false,
    can_use_background_jobs: false,
    can_create_invoice: true,
    can_create_quote: true,
    can_create_api_key: true,
    can_create_webhook: false,
    remaining_invoice_quota: 44,
    remaining_quote_quota: 47,
    remaining_users: 1,
    remaining_api_keys: 1,
    remaining_webhooks: 0,
  },
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

function mockUsageAndEntitlements(
  entitlements: OrganizationEntitlements,
  usage: OrganizationUsage,
  subscription: Subscription = activeSubscription
) {
  apiFetchMock.mockImplementation((path: string) => {
    if (path.endsWith("/entitlements")) return Promise.resolve(entitlements);
    if (path.endsWith("/usage")) return Promise.resolve(usage);
    if (path.endsWith("/subscription")) return Promise.resolve(subscription);
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

describe("PlanAndLimitsPage", () => {
  it("fetches from both the entitlements and usage endpoints and renders used/limit read-only", async () => {
    mockUsageAndEntitlements(freeEntitlements, freeUsage);
    renderWithProviders(<PlanAndLimitsPage />);

    await waitFor(() => expect(screen.getByText("Free")).toBeInTheDocument());
    expect(apiFetchMock).toHaveBeenCalledWith("/organizations/org-1/entitlements", expect.anything());
    expect(apiFetchMock).toHaveBeenCalledWith("/organizations/org-1/usage", expect.anything());
    expect(screen.getByText("1 / 2")).toBeInTheDocument();
    expect(screen.getByText("18 / 100")).toBeInTheDocument();
    expect(screen.getByText("0 / 500 MB")).toBeInTheDocument();

    // Read-only: no edit controls, no upgrade CTA.
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByText(/upgrade/i)).not.toBeInTheDocument();
  });

  it("renders a loading state before data arrives", async () => {
    let resolveEntitlements: (value: OrganizationEntitlements) => void = () => {};
    apiFetchMock.mockImplementation((path: string) => {
      if (path.endsWith("/entitlements")) return new Promise((resolve) => (resolveEntitlements = resolve));
      return new Promise(() => {});
    });
    renderWithProviders(<PlanAndLimitsPage />);

    expect(screen.queryByText("Free")).not.toBeInTheDocument();
    resolveEntitlements(freeEntitlements);
  });

  it("renders unlimited limits and disabled features consistently", async () => {
    const unlimitedEntitlements: OrganizationEntitlements = {
      ...freeEntitlements,
      plan_name: "Enterprise",
      limits: {
        max_users: null,
        max_customers: null,
        max_products: null,
        max_invoices_per_month: null,
        max_quotes_per_month: null,
        max_ai_actions_per_month: null,
        storage_limit_mb: null,
        max_api_keys: null,
        max_webhooks: null,
      },
      features: {
        custom_branding_enabled: true,
        api_access_enabled: true,
        advanced_reports_enabled: true,
        analytics_enabled: true,
        forecasting_enabled: true,
        ai_enabled: true,
        background_jobs_enabled: true,
      },
    };
    const unlimitedUsage: OrganizationUsage = {
      users: { used: 40, limit: null, unlimited: true },
      customers: { used: 500, limit: null, unlimited: true },
      products: { used: 20, limit: null, unlimited: true },
      invoices: { used: 30, limit: null, unlimited: true },
      quotes: { used: 10, limit: null, unlimited: true },
      ai_actions: { used: 100, limit: null, unlimited: true },
      storage: { used: 0, limit: null, unlimited: true },
    };
    mockUsageAndEntitlements(unlimitedEntitlements, unlimitedUsage);
    renderWithProviders(<PlanAndLimitsPage />);

    await waitFor(() => expect(screen.getByText("Enterprise")).toBeInTheDocument());
    // 6 numeric usage rows + storage, all "Unlimited" -- usage numbers
    // are never shown alongside "Unlimited" since there's no ceiling to
    // measure against.
    expect(screen.getAllByText("Unlimited")).toHaveLength(7);
  });

  it("renders a zero limit as unavailable, not as zero", async () => {
    mockUsageAndEntitlements(
      { ...freeEntitlements, limits: { ...freeEntitlements.limits, max_ai_actions_per_month: 0 } },
      { ...freeUsage, ai_actions: { used: 0, limit: 0, unlimited: false } }
    );
    renderWithProviders(<PlanAndLimitsPage />);

    await waitFor(() => expect(screen.getByText("Free")).toBeInTheDocument());
    expect(screen.getByText("Not available")).toBeInTheDocument();
    expect(screen.queryByText("0 / 0")).not.toBeInTheDocument();
  });

  it("shows an error message when the load fails", async () => {
    const { ApiError } = await import("@/lib/api");
    apiFetchMock.mockRejectedValue(new ApiError("Server exploded", 500));
    renderWithProviders(<PlanAndLimitsPage />);

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Server exploded"));
  });

  it("shows a Reached badge when usage equals its limit, and Almost full when over 90%", async () => {
    mockUsageAndEntitlements(freeEntitlements, {
      ...freeUsage,
      // exactly at the limit
      users: { used: 2, limit: 2, unlimited: false },
      // 92% of 25 -> "near", not "reached"
      ai_actions: { used: 23, limit: 25, unlimited: false },
      // comfortably below -- no badge at all
      customers: { used: 18, limit: 100, unlimited: false },
    });
    renderWithProviders(<PlanAndLimitsPage />);

    await waitFor(() => expect(screen.getByText("Free")).toBeInTheDocument());
    expect(screen.getByText("Reached")).toBeInTheDocument();
    expect(screen.getByText("Almost full")).toBeInTheDocument();
    // Still purely visual -- no blocking UI, no button anywhere on the page.
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("shows no Reached/Almost full badge for unlimited or comfortably-under-limit resources", async () => {
    mockUsageAndEntitlements(freeEntitlements, freeUsage);
    renderWithProviders(<PlanAndLimitsPage />);

    await waitFor(() => expect(screen.getByText("Free")).toBeInTheDocument());
    expect(screen.queryByText("Reached")).not.toBeInTheDocument();
    expect(screen.queryByText("Almost full")).not.toBeInTheDocument();
  });

  it("renders the subscription status, billing period, and current period end", async () => {
    mockUsageAndEntitlements(freeEntitlements, freeUsage, activeSubscription);
    renderWithProviders(<PlanAndLimitsPage />);

    await waitFor(() => expect(screen.getByText("Active")).toBeInTheDocument());
    expect(screen.getByText("Monthly")).toBeInTheDocument();
    expect(apiFetchMock).toHaveBeenCalledWith("/organizations/org-1/subscription", expect.anything());
    // Not trialing -- no trial-remaining row at all.
    expect(screen.queryByText(/days left/)).not.toBeInTheDocument();
    // Not flagged to cancel -- no "will not renew" badge.
    expect(screen.queryByText("Will not renew")).not.toBeInTheDocument();
  });

  it("renders trial days remaining while trialing", async () => {
    const trialEnd = new Date(Date.now() + 5 * 24 * 60 * 60 * 1000).toISOString();
    mockUsageAndEntitlements(freeEntitlements, freeUsage, {
      ...activeSubscription,
      status: "trialing",
      trial_start: new Date().toISOString(),
      trial_end: trialEnd,
    });
    renderWithProviders(<PlanAndLimitsPage />);

    await waitFor(() => expect(screen.getByText("Trialing")).toBeInTheDocument());
    expect(screen.getByText("5 days left")).toBeInTheDocument();
  });

  it("renders a Will not renew badge when cancel_at_period_end is set", async () => {
    mockUsageAndEntitlements(freeEntitlements, freeUsage, {
      ...activeSubscription,
      cancel_at_period_end: true,
    });
    renderWithProviders(<PlanAndLimitsPage />);

    await waitFor(() => expect(screen.getByText("Will not renew")).toBeInTheDocument());
  });

  it("renders the four Phase 17A feature badges alongside the existing three", async () => {
    mockUsageAndEntitlements(freeEntitlements, freeUsage);
    renderWithProviders(<PlanAndLimitsPage />);

    await waitFor(() => expect(screen.getByText("Free")).toBeInTheDocument());
    expect(screen.getByText("Analytics")).toBeInTheDocument();
    expect(screen.getByText("Forecasting")).toBeInTheDocument();
    expect(screen.getByText("AI Assistant")).toBeInTheDocument();
    expect(screen.getByText("Background jobs")).toBeInTheDocument();
  });
});
