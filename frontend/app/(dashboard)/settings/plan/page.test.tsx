import { beforeEach, describe, expect, it, vi } from "vitest";

import { setAuthSession } from "@/lib/auth-storage";
import type { OrganizationEntitlements } from "@/lib/types";
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
  },
  features: {
    custom_branding_enabled: false,
    api_access_enabled: false,
    advanced_reports_enabled: false,
  },
};

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
  it("fetches from the entitlements endpoint and renders the plan name and limits read-only", async () => {
    apiFetchMock.mockResolvedValueOnce(freeEntitlements);
    renderWithProviders(<PlanAndLimitsPage />);

    await waitFor(() => expect(screen.getByText("Free")).toBeInTheDocument());
    expect(apiFetchMock.mock.calls[0][0]).toBe("/organizations/org-1/entitlements");
    expect(screen.getByText("500 MB")).toBeInTheDocument();

    // Read-only: no edit controls, no upgrade CTA, no usage numbers.
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByText(/upgrade/i)).not.toBeInTheDocument();
  });

  it("renders unlimited limits and disabled features consistently", async () => {
    apiFetchMock.mockResolvedValueOnce({
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
      },
      features: { custom_branding_enabled: true, api_access_enabled: true, advanced_reports_enabled: true },
    } satisfies OrganizationEntitlements);
    renderWithProviders(<PlanAndLimitsPage />);

    await waitFor(() => expect(screen.getByText("Enterprise")).toBeInTheDocument());
    // 6 numeric limit rows + storage, all "Unlimited".
    expect(screen.getAllByText("Unlimited")).toHaveLength(7);
  });

  it("renders a zero limit as unavailable, not as zero", async () => {
    apiFetchMock.mockResolvedValueOnce({
      ...freeEntitlements,
      limits: { ...freeEntitlements.limits, max_ai_actions_per_month: 0 },
    } satisfies OrganizationEntitlements);
    renderWithProviders(<PlanAndLimitsPage />);

    await waitFor(() => expect(screen.getByText("Free")).toBeInTheDocument());
    expect(screen.getByText("Not available")).toBeInTheDocument();
    expect(screen.queryByText("0")).not.toBeInTheDocument();
  });

  it("shows an error message when the load fails", async () => {
    const { ApiError } = await import("@/lib/api");
    apiFetchMock.mockRejectedValueOnce(new ApiError("Server exploded", 500));
    renderWithProviders(<PlanAndLimitsPage />);

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Server exploded"));
  });
});
