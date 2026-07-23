import { within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PlatformOrganizationDetail } from "@/lib/types";
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
