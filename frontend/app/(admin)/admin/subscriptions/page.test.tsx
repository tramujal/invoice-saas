import { within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PaginatedPlatformSubscriptions } from "@/lib/types";
import { renderWithProviders, screen, waitFor } from "@/tests/test-utils";

import PlatformSubscriptionsPage from "./page";

vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/subscriptions",
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

const activeSubscription: PaginatedPlatformSubscriptions["items"][number] = {
  id: "sub-1",
  organization_id: "org-1",
  organization_name: "Acme Inc",
  plan_code: "starter",
  plan_name: "Starter",
  status: "active",
  billing_period: "monthly",
  trial_end: null,
  current_period_end: "2026-02-01T00:00:00Z",
  cancel_at_period_end: false,
  created_at: "2026-01-01T00:00:00Z",
};

const canceledSubscription: PaginatedPlatformSubscriptions["items"][number] = {
  id: "sub-2",
  organization_id: "org-2",
  organization_name: "Widgets Co",
  plan_code: "free",
  plan_name: "Free",
  status: "canceled",
  billing_period: "yearly",
  trial_end: null,
  current_period_end: "2026-03-01T00:00:00Z",
  cancel_at_period_end: true,
  created_at: "2026-01-01T00:00:00Z",
};

beforeEach(() => {
  apiFetchMock.mockReset();
});

describe("PlatformSubscriptionsPage", () => {
  it("shows a loading state, then renders subscription rows", async () => {
    apiFetchMock.mockResolvedValueOnce({
      total: 2,
      items: [activeSubscription, canceledSubscription],
    } satisfies PaginatedPlatformSubscriptions);
    renderWithProviders(<PlatformSubscriptionsPage />);

    expect(screen.getByText("Loading subscriptions…")).toBeInTheDocument();

    await waitFor(() => expect(screen.getByText("Acme Inc")).toBeInTheDocument());
    expect(screen.getByText("Widgets Co")).toBeInTheDocument();
    expect(screen.getByText("Starter")).toBeInTheDocument();

    const activeRow = screen.getByText("Acme Inc").closest("tr")!;
    expect(within(activeRow).getByText("Active")).toBeInTheDocument();

    const canceledRow = screen.getByText("Widgets Co").closest("tr")!;
    expect(within(canceledRow).getByText("Canceled")).toBeInTheDocument();
    expect(within(canceledRow).getByText("Will not renew")).toBeInTheDocument();
  });

  it("shows an empty state when there are no subscriptions", async () => {
    apiFetchMock.mockResolvedValueOnce({ total: 0, items: [] } satisfies PaginatedPlatformSubscriptions);
    renderWithProviders(<PlatformSubscriptionsPage />);

    await waitFor(() => expect(screen.getByText("No subscriptions yet")).toBeInTheDocument());
  });

  it("shows an error message when the load fails", async () => {
    const { ApiError } = await import("@/lib/api");
    apiFetchMock.mockRejectedValue(new ApiError("Server exploded", 500));
    renderWithProviders(<PlatformSubscriptionsPage />);

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Server exploded"));
  });

  it("refetches with a status query param when the status filter changes", async () => {
    const { default: userEvent } = await import("@testing-library/user-event");
    apiFetchMock.mockResolvedValue({ total: 0, items: [] } satisfies PaginatedPlatformSubscriptions);
    renderWithProviders(<PlatformSubscriptionsPage />);

    await waitFor(() => expect(apiFetchMock).toHaveBeenCalled());
    apiFetchMock.mockClear();

    const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText("Filter by subscription status"), "canceled");

    await waitFor(() =>
      expect(apiFetchMock).toHaveBeenCalledWith(
        expect.stringContaining("status=canceled"),
        expect.anything()
      )
    );
  });
});
