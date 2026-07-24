import { within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { OrganizationUsage, Plan, PlansListResponse, PlatformOrganizationDetail } from "@/lib/types";
import { renderWithProviders, screen, waitFor } from "@/tests/test-utils";

import PlatformOrganizationDetailPage from "./page";

vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/organizations/org-1",
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  useParams: () => ({ id: "org-1" }),
}));

const apiFetchMock = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    apiFetch: (...args: unknown[]) => apiFetchMock(...args),
  };
});

const emptyUsage: OrganizationUsage = {
  users: { used: 1, limit: 2, unlimited: false },
  customers: { used: 0, limit: 100, unlimited: false },
  products: { used: 0, limit: 100, unlimited: false },
  invoices: { used: 0, limit: 50, unlimited: false },
  quotes: { used: 0, limit: 50, unlimited: false },
  ai_actions: { used: 0, limit: 25, unlimited: false },
  storage: { used: 0, limit: 500, unlimited: false },
};

const activeOrg: PlatformOrganizationDetail = {
  id: "org-1",
  name: "Rivera Design Studio",
  business_name: null,
  status: "active",
  owner_email: "owner@example.com",
  members_count: 1,
  invoices_count: 0,
  quotes_count: 0,
  customers_count: 0,
  products_count: 0,
  language: "en",
  currency_code: "USD",
  timezone: "UTC",
  plan_id: "plan_free",
  plan_code: "free",
  plan_name: "Free",
  usage: emptyUsage,
  created_at: "2026-01-01T00:00:00Z",
  last_activity_at: null,
  members: [],
  recent_documents: [],
};

beforeEach(() => {
  apiFetchMock.mockReset();
});

describe("PlatformOrganizationDetailPage suspend/reactivate", () => {
  it("shows a Suspend button for an active organization and disables submit until name and reason are provided", async () => {
    apiFetchMock.mockResolvedValue(activeOrg);
    const user = userEvent.setup();
    renderWithProviders(<PlatformOrganizationDetailPage />);

    await waitFor(() => expect(screen.getByRole("button", { name: "Suspend" })).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Suspend" }));

    const dialog = screen.getByRole("dialog");
    const confirmButton = within(dialog).getByRole("button", { name: "Suspend organization" });
    expect(confirmButton).toBeDisabled();

    await user.type(within(dialog).getByLabelText("Type Rivera Design Studio to confirm"), "wrong name");
    await user.type(within(dialog).getByLabelText("Reason"), "policy violation");
    expect(confirmButton).toBeDisabled();

    await user.clear(within(dialog).getByLabelText("Type Rivera Design Studio to confirm"));
    await user.type(within(dialog).getByLabelText("Type Rivera Design Studio to confirm"), "Rivera Design Studio");
    expect(confirmButton).not.toBeDisabled();
  });

  it("suspends successfully, updates the status badge from the mutation response, and closes the dialog", async () => {
    apiFetchMock.mockResolvedValueOnce(activeOrg);
    const user = userEvent.setup();
    renderWithProviders(<PlatformOrganizationDetailPage />);

    await waitFor(() => expect(screen.getByRole("button", { name: "Suspend" })).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Suspend" }));

    const dialog = screen.getByRole("dialog");
    await user.type(within(dialog).getByLabelText("Type Rivera Design Studio to confirm"), "Rivera Design Studio");
    await user.type(within(dialog).getByLabelText("Reason"), "policy violation");

    apiFetchMock.mockResolvedValueOnce({ ...activeOrg, status: "suspended" });
    await user.click(within(dialog).getByRole("button", { name: "Suspend organization" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.getByText("Suspended")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reactivate" })).toBeInTheDocument();

    // Exactly one call for the initial load, one for the mutation -- never
    // a second GET just to see the mutation's own result.
    expect(apiFetchMock).toHaveBeenCalledTimes(2);
    expect(apiFetchMock.mock.calls[1][0]).toBe("/admin/organizations/org-1/suspend");
  });

  it("shows a controlled error and keeps the dialog open when the mutation fails", async () => {
    const { ApiError } = await import("@/lib/api");
    apiFetchMock.mockResolvedValueOnce(activeOrg);
    const user = userEvent.setup();
    renderWithProviders(<PlatformOrganizationDetailPage />);

    await waitFor(() => expect(screen.getByRole("button", { name: "Suspend" })).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Suspend" }));

    const dialog = screen.getByRole("dialog");
    await user.type(within(dialog).getByLabelText("Type Rivera Design Studio to confirm"), "Rivera Design Studio");
    await user.type(within(dialog).getByLabelText("Reason"), "policy violation");

    apiFetchMock.mockRejectedValueOnce(new ApiError("This organization is already suspended.", 409));
    await user.click(within(dialog).getByRole("button", { name: "Suspend organization" }));

    await waitFor(() =>
      expect(within(dialog).getByRole("alert")).toHaveTextContent("This organization is already suspended.")
    );
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    // Status must not have changed optimistically.
    expect(screen.getByText("Active")).toBeInTheDocument();
  });
});

function makePlan(overrides: Partial<Plan> = {}): Plan {
  return {
    id: "plan_pro",
    code: "pro",
    name: "Pro",
    description: null,
    is_active: true,
    is_default: false,
    sort_order: 2,
    limits: {
      max_users: 50,
      max_customers: 10000,
      max_products: 10000,
      max_invoices_per_month: 10000,
      max_quotes_per_month: 10000,
      max_ai_actions_per_month: 5000,
      storage_limit_mb: null,
    },
    features: { custom_branding_enabled: true, api_access_enabled: true, advanced_reports_enabled: true },
    version: 1,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("PlatformOrganizationDetailPage change plan", () => {
  it("shows the current plan name and a Change plan button", async () => {
    apiFetchMock.mockResolvedValueOnce(activeOrg);
    renderWithProviders(<PlatformOrganizationDetailPage />);

    await waitFor(() => expect(screen.getByText("Free")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Change plan" })).toBeInTheDocument();
  });

  it("lazily loads active plans, excludes the current plan from the options, and requires typed name + reason", async () => {
    apiFetchMock.mockResolvedValueOnce(activeOrg);
    const user = userEvent.setup();
    renderWithProviders(<PlatformOrganizationDetailPage />);

    await waitFor(() => expect(screen.getByRole("button", { name: "Change plan" })).toBeInTheDocument());
    expect(apiFetchMock).toHaveBeenCalledTimes(1);

    const proPlan = makePlan();
    const inactivePlan = makePlan({ id: "plan_legacy", code: "legacy", name: "Legacy", is_active: false });
    apiFetchMock.mockResolvedValueOnce({ items: [proPlan, inactivePlan] } satisfies PlansListResponse);
    await user.click(screen.getByRole("button", { name: "Change plan" }));

    const dialog = await screen.findByRole("dialog");
    expect(apiFetchMock.mock.calls[1][0]).toBe("/admin/plans");

    const select = within(dialog).getByLabelText("New plan");
    expect(within(select).getByText("Pro")).toBeInTheDocument();
    expect(within(select).queryByText("Legacy")).not.toBeInTheDocument();
    expect(within(select).queryByText("Free")).not.toBeInTheDocument();

    const confirmButton = within(dialog).getByRole("button", { name: "Change plan" });
    expect(confirmButton).toBeDisabled();

    await user.selectOptions(select, "plan_pro");
    expect(confirmButton).toBeDisabled();

    await user.type(within(dialog).getByLabelText("Type Rivera Design Studio to confirm"), "Rivera Design Studio");
    await user.type(within(dialog).getByLabelText("Reason"), "upgrading customer");
    expect(confirmButton).not.toBeDisabled();
  });

  it("changes the plan successfully, replaces state from the mutation response, and never auto-retries", async () => {
    apiFetchMock.mockResolvedValueOnce(activeOrg);
    const user = userEvent.setup();
    renderWithProviders(<PlatformOrganizationDetailPage />);

    await waitFor(() => expect(screen.getByRole("button", { name: "Change plan" })).toBeInTheDocument());

    const proPlan = makePlan();
    apiFetchMock.mockResolvedValueOnce({ items: [proPlan] } satisfies PlansListResponse);
    await user.click(screen.getByRole("button", { name: "Change plan" }));

    const dialog = await screen.findByRole("dialog");
    await user.selectOptions(within(dialog).getByLabelText("New plan"), "plan_pro");
    await user.type(within(dialog).getByLabelText("Type Rivera Design Studio to confirm"), "Rivera Design Studio");
    await user.type(within(dialog).getByLabelText("Reason"), "upgrading customer");

    apiFetchMock.mockResolvedValueOnce({ ...activeOrg, plan_id: "plan_pro", plan_code: "pro", plan_name: "Pro" });
    await user.click(within(dialog).getByRole("button", { name: "Change plan" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.getByText("Pro")).toBeInTheDocument();
    expect(apiFetchMock).toHaveBeenCalledTimes(3);
    expect(apiFetchMock.mock.calls[2][0]).toBe("/admin/organizations/org-1/plan");
    expect(apiFetchMock.mock.calls[2][1]).toMatchObject({
      method: "PATCH",
      body: JSON.stringify({ plan_id: "plan_pro", reason: "upgrading customer" }),
    });
  });

  it("shows a controlled error and keeps the dialog open when the plan-change mutation fails", async () => {
    const { ApiError } = await import("@/lib/api");
    apiFetchMock.mockResolvedValueOnce(activeOrg);
    const user = userEvent.setup();
    renderWithProviders(<PlatformOrganizationDetailPage />);

    await waitFor(() => expect(screen.getByRole("button", { name: "Change plan" })).toBeInTheDocument());

    const proPlan = makePlan();
    apiFetchMock.mockResolvedValueOnce({ items: [proPlan] } satisfies PlansListResponse);
    await user.click(screen.getByRole("button", { name: "Change plan" }));

    const dialog = await screen.findByRole("dialog");
    await user.selectOptions(within(dialog).getByLabelText("New plan"), "plan_pro");
    await user.type(within(dialog).getByLabelText("Type Rivera Design Studio to confirm"), "Rivera Design Studio");
    await user.type(within(dialog).getByLabelText("Reason"), "upgrading customer");

    apiFetchMock.mockRejectedValueOnce(new ApiError("This plan is inactive.", 409));
    await user.click(within(dialog).getByRole("button", { name: "Change plan" }));

    await waitFor(() =>
      expect(within(dialog).getByRole("alert")).toHaveTextContent("This plan is inactive.")
    );
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Free")).toBeInTheDocument();
  });
});

describe("PlatformOrganizationDetailPage usage", () => {
  it("renders used/limit for finite resources", async () => {
    apiFetchMock.mockResolvedValue({
      ...activeOrg,
      usage: { ...emptyUsage, users: { used: 18, limit: 50, unlimited: false } },
    } satisfies PlatformOrganizationDetail);
    renderWithProviders(<PlatformOrganizationDetailPage />);

    await waitFor(() => expect(screen.getByText("18 / 50")).toBeInTheDocument());
  });

  it("renders Unlimited for unlimited resources", async () => {
    apiFetchMock.mockResolvedValue({
      ...activeOrg,
      usage: {
        ...emptyUsage,
        customers: { used: 340, limit: null, unlimited: true },
      },
    } satisfies PlatformOrganizationDetail);
    renderWithProviders(<PlatformOrganizationDetailPage />);

    await waitFor(() => expect(screen.getByText("Unlimited")).toBeInTheDocument());
  });

  it("shows loading placeholders before usage data arrives", () => {
    apiFetchMock.mockImplementation(() => new Promise(() => {}));
    renderWithProviders(<PlatformOrganizationDetailPage />);

    expect(screen.queryByText("1 / 2")).not.toBeInTheDocument();
  });
});
