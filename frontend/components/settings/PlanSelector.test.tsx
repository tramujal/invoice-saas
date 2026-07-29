import { beforeEach, describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";

import { setAuthSession } from "@/lib/auth-storage";
import type { Plan, Subscription } from "@/lib/types";
import { renderWithProviders, screen, waitFor } from "@/tests/test-utils";

import { PlanSelector } from "./PlanSelector";

const apiFetchMock = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    apiFetch: (...args: unknown[]) => apiFetchMock(...args),
  };
});

function makePlan(overrides: Partial<Plan> = {}): Plan {
  return {
    id: "plan_free",
    code: "free",
    name: "Free",
    description: "For getting started",
    is_active: true,
    is_default: true,
    sort_order: 0,
    public: true,
    monthly_price: "0.00",
    yearly_price: "0.00",
    currency: "USD",
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
    version: 1,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

const proPlan = makePlan({
  id: "plan_pro",
  code: "pro",
  name: "Pro",
  description: "For growing teams",
  is_default: false,
  sort_order: 2,
  monthly_price: "49.00",
  yearly_price: "490.00",
});

const subscription: Subscription = {
  id: "sub-1",
  organization_id: "org-1",
  plan: makePlan(),
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

beforeEach(() => {
  window.localStorage.clear();
  apiFetchMock.mockReset();
});

function loginWithBillingManage() {
  setAuthSession({
    token: "test-token",
    apiBaseUrl: "http://localhost:8000",
    organizationId: "org-1",
    userEmail: "owner@example.com",
    organizationPermissions: ["billing.manage"],
  });
}

describe("PlanSelector", () => {
  it("renders nothing for a user without billing.manage", () => {
    setAuthSession({
      token: "test-token",
      apiBaseUrl: "http://localhost:8000",
      organizationId: "org-1",
      userEmail: "member@example.com",
      organizationPermissions: ["invoice.read"],
    });
    renderWithProviders(<PlanSelector subscription={subscription} />);
    expect(screen.queryByRole("heading")).not.toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(apiFetchMock).not.toHaveBeenCalled();
  });

  it("fetches and renders the plan catalog for a billing.manage user", async () => {
    loginWithBillingManage();
    apiFetchMock.mockResolvedValue([makePlan(), proPlan]);
    renderWithProviders(<PlanSelector subscription={subscription} />);

    await waitFor(() => expect(screen.getByText("Pro")).toBeInTheDocument());
    expect(apiFetchMock).toHaveBeenCalledWith("/organizations/org-1/billing/plans");
    // Both the badge and the (disabled) button on the Free card say
    // "Current plan" -- two matches is the correct, expected shape.
    expect(screen.getAllByText("Current plan").length).toBe(2);
  });

  it("disables the button for the organization's current plan", async () => {
    loginWithBillingManage();
    apiFetchMock.mockResolvedValue([makePlan(), proPlan]);
    renderWithProviders(<PlanSelector subscription={subscription} />);

    await waitFor(() => expect(screen.getByText("Pro")).toBeInTheDocument());
    const currentPlanButtons = screen.getAllByRole("button", { name: "Current plan" });
    expect(currentPlanButtons[0]).toBeDisabled();
  });

  it("starts checkout and redirects to the returned checkout_url", async () => {
    loginWithBillingManage();
    apiFetchMock.mockImplementation((path: string) => {
      if (path.endsWith("/billing/plans")) return Promise.resolve([makePlan(), proPlan]);
      if (path.endsWith("/billing/checkout")) {
        return Promise.resolve({ checkout_url: "https://checkout.stripe.com/session/abc" });
      }
      return Promise.reject(new Error(`unexpected call: ${path}`));
    });
    const originalLocation = window.location;
    // jsdom doesn't implement navigation -- replace window.location with a
    // writable stand-in so assigning .href doesn't throw, matching this
    // repo's existing convention for testing redirect-driven flows.
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...originalLocation, href: "http://localhost/settings/plan" },
    });

    const user = userEvent.setup();
    renderWithProviders(<PlanSelector subscription={subscription} />);

    await waitFor(() => expect(screen.getByText("Pro")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Choose plan" }));

    await waitFor(() => expect(window.location.href).toBe("https://checkout.stripe.com/session/abc"));
    const checkoutCall = apiFetchMock.mock.calls.find((call) => String(call[0]).endsWith("/billing/checkout"));
    expect(checkoutCall).toBeDefined();
    const body = JSON.parse((checkoutCall![1] as RequestInit).body as string);
    expect(body.plan_id).toBe("plan_pro");
    expect(body.billing_period).toBe("monthly");

    Object.defineProperty(window, "location", { configurable: true, value: originalLocation });
  });

  it("shows an error toast when starting checkout fails", async () => {
    loginWithBillingManage();
    apiFetchMock.mockImplementation((path: string) => {
      if (path.endsWith("/billing/plans")) return Promise.resolve([makePlan(), proPlan]);
      if (path.endsWith("/billing/checkout")) return Promise.reject(new Error("boom"));
      return Promise.reject(new Error(`unexpected call: ${path}`));
    });

    const user = userEvent.setup();
    renderWithProviders(<PlanSelector subscription={subscription} />);

    await waitFor(() => expect(screen.getByText("Pro")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Choose plan" }));

    expect(await screen.findByText("Could not start checkout. Please try again.")).toBeInTheDocument();
  });

  it("shows an error message when the plan catalog fails to load", async () => {
    loginWithBillingManage();
    apiFetchMock.mockRejectedValue(new Error("boom"));
    renderWithProviders(<PlanSelector subscription={subscription} />);

    await waitFor(() =>
      expect(screen.getByText("Failed to load available plans")).toBeInTheDocument()
    );
  });
});
