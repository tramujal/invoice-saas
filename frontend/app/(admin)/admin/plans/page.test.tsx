import { within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Plan, PlansListResponse } from "@/lib/types";
import { renderWithProviders, screen, waitFor } from "@/tests/test-utils";

import PlatformPlansPage from "./page";

vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/plans",
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

function makePlan(overrides: Partial<Plan> = {}): Plan {
  return {
    id: "plan_free",
    code: "free",
    name: "Free",
    description: null,
    is_active: true,
    is_default: true,
    sort_order: 0,
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
    version: 1,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

const freePlan = makePlan();
const proPlan = makePlan({
  id: "plan_pro",
  code: "pro",
  name: "Pro",
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
});

beforeEach(() => {
  apiFetchMock.mockReset();
});

describe("PlatformPlansPage", () => {
  it("shows a loading state, then renders plans with unlimited storage rendered consistently", async () => {
    apiFetchMock.mockResolvedValueOnce({ items: [freePlan, proPlan] } satisfies PlansListResponse);
    renderWithProviders(<PlatformPlansPage />);

    expect(screen.getByText("Loading plans…")).toBeInTheDocument();

    await waitFor(() => expect(screen.getByText("Free")).toBeInTheDocument());
    expect(screen.getByText("Pro")).toBeInTheDocument();
    expect(screen.getByText("Default")).toBeInTheDocument();
    expect(screen.getByText("Unlimited")).toBeInTheDocument();
  });

  it("shows an empty state when there are no plans", async () => {
    apiFetchMock.mockResolvedValueOnce({ items: [] } satisfies PlansListResponse);
    renderWithProviders(<PlatformPlansPage />);

    await waitFor(() => expect(screen.getByText("No plans yet")).toBeInTheDocument());
  });

  it("shows an error message when the list request fails", async () => {
    const { ApiError } = await import("@/lib/api");
    apiFetchMock.mockRejectedValueOnce(new ApiError("Server exploded", 500));
    renderWithProviders(<PlatformPlansPage />);

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Server exploded"));
  });

  it("creates a plan and requires a reason before submitting", async () => {
    apiFetchMock.mockResolvedValueOnce({ items: [freePlan] } satisfies PlansListResponse);
    const user = userEvent.setup();
    renderWithProviders(<PlatformPlansPage />);

    await waitFor(() => expect(screen.getByText("Free")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Create plan" }));

    const dialog = screen.getByRole("dialog");
    const confirmButton = within(dialog).getByRole("button", { name: "Create plan" });
    expect(confirmButton).toBeDisabled();

    await user.type(within(dialog).getByLabelText("Code"), "starter-plus");
    await user.type(within(dialog).getByLabelText("Name"), "Starter Plus");
    expect(confirmButton).toBeDisabled();

    await user.type(within(dialog).getByLabelText("Reason"), "new tier");
    expect(confirmButton).not.toBeDisabled();

    const created = makePlan({ id: "plan_starter_plus", code: "starter-plus", name: "Starter Plus", is_default: false });
    apiFetchMock.mockResolvedValueOnce(created);
    await user.click(confirmButton);

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.getByText("Starter Plus")).toBeInTheDocument();
    expect(apiFetchMock.mock.calls[1][0]).toBe("/admin/plans");
    expect(apiFetchMock.mock.calls[1][1]).toMatchObject({ method: "POST" });
  });

  it("edits a plan without exposing the code as editable, and shows the version-conflict error", async () => {
    apiFetchMock.mockResolvedValueOnce({ items: [freePlan] } satisfies PlansListResponse);
    const user = userEvent.setup();
    renderWithProviders(<PlatformPlansPage />);

    await waitFor(() => expect(screen.getByText("Free")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "More actions" }));
    await user.click(screen.getByRole("menuitem", { name: "Edit" }));

    const dialog = screen.getByRole("dialog");
    expect(within(dialog).queryByLabelText("Code")).not.toBeInTheDocument();
    expect(within(dialog).getByText("free")).toBeInTheDocument();

    await user.clear(within(dialog).getByLabelText("Max users"));
    await user.type(within(dialog).getByLabelText("Max users"), "5");
    await user.type(within(dialog).getByLabelText("Reason"), "raise seat limit");

    const { ApiError } = await import("@/lib/api");
    apiFetchMock.mockRejectedValueOnce(
      new ApiError("Version conflict", 409, {
        detail: { code: "plan_version_conflict", message: "Version conflict", current_version: 2 },
      })
    );
    await user.click(within(dialog).getByRole("button", { name: "Save changes" }));

    // A dedicated conflict dialog, not an inline error -- the stale
    // edit dialog underneath is left exactly as the admin had it (no
    // silent overwrite), and there is no automatic retry.
    const conflictDialog = await screen.findByRole("alertdialog");
    expect(conflictDialog).toHaveTextContent("Someone else just changed this plan");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(within(dialog).getByLabelText("Max users")).toHaveValue(5);
  });

  it("reloads the latest plan from a version conflict without discarding the dialog, then lets the admin resubmit", async () => {
    apiFetchMock.mockResolvedValueOnce({ items: [freePlan] } satisfies PlansListResponse);
    const user = userEvent.setup();
    renderWithProviders(<PlatformPlansPage />);

    await waitFor(() => expect(screen.getByText("Free")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "More actions" }));
    await user.click(screen.getByRole("menuitem", { name: "Edit" }));

    const dialog = screen.getByRole("dialog");
    await user.type(within(dialog).getByLabelText("Reason"), "raise seat limit");

    const { ApiError } = await import("@/lib/api");
    apiFetchMock.mockRejectedValueOnce(
      new ApiError("Version conflict", 409, {
        detail: { code: "plan_version_conflict", message: "Version conflict", current_version: 2 },
      })
    );
    await user.click(within(dialog).getByRole("button", { name: "Save changes" }));
    const conflictDialog = await screen.findByRole("alertdialog");

    const freshPlan = makePlan({ version: 2, limits: { ...freePlan.limits, max_users: 3 } });
    apiFetchMock.mockResolvedValueOnce(freshPlan);
    await user.click(within(conflictDialog).getByRole("button", { name: "Reload latest plan" }));

    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    // The edit dialog stays open, now reflecting the reloaded plan.
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(within(screen.getByRole("dialog")).getByLabelText("Max users")).toHaveValue(3);
  });

  it("deactivates a plan via the row actions menu", async () => {
    apiFetchMock.mockResolvedValueOnce({ items: [freePlan] } satisfies PlansListResponse);
    const user = userEvent.setup();
    renderWithProviders(<PlatformPlansPage />);

    await waitFor(() => expect(screen.getByText("Free")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "More actions" }));
    await user.click(screen.getByRole("menuitem", { name: "Deactivate" }));

    const dialog = screen.getByRole("dialog");
    await user.type(within(dialog).getByLabelText("Reason"), "retiring this tier");

    apiFetchMock.mockResolvedValueOnce({ ...freePlan, is_active: false });
    await user.click(within(dialog).getByRole("button", { name: "Deactivate" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.getByText("Inactive")).toBeInTheDocument();
    expect(apiFetchMock.mock.calls[1][0]).toBe("/admin/plans/plan_free/deactivate");
  });

  it("does not offer 'Make default' for the current default plan, but does for an active non-default plan", async () => {
    apiFetchMock.mockResolvedValueOnce({ items: [freePlan, proPlan] } satisfies PlansListResponse);
    const user = userEvent.setup();
    renderWithProviders(<PlatformPlansPage />);

    await waitFor(() => expect(screen.getByText("Pro")).toBeInTheDocument());
    const menus = screen.getAllByRole("button", { name: "More actions" });

    await user.click(menus[0]);
    expect(screen.queryByRole("menuitem", { name: "Make default" })).not.toBeInTheDocument();
    await user.keyboard("{Escape}");

    await user.click(menus[1]);
    expect(screen.getByRole("menuitem", { name: "Make default" })).toBeInTheDocument();
  });
});
