import { beforeEach, describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";

import { ApiError } from "@/lib/api";
import { setAuthSession } from "@/lib/auth-storage";
import { renderWithProviders, screen, waitFor } from "@/tests/test-utils";

import { ManageBillingButton } from "./ManageBillingButton";

const apiFetchMock = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    apiFetch: (...args: unknown[]) => apiFetchMock(...args),
  };
});

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

describe("ManageBillingButton", () => {
  it("renders nothing for a user without billing.manage", () => {
    setAuthSession({
      token: "test-token",
      apiBaseUrl: "http://localhost:8000",
      organizationId: "org-1",
      userEmail: "member@example.com",
      organizationPermissions: ["invoice.read"],
    });
    renderWithProviders(<ManageBillingButton />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(apiFetchMock).not.toHaveBeenCalled();
  });

  it("starts a portal session and redirects to the returned portal_url", async () => {
    loginWithBillingManage();
    apiFetchMock.mockResolvedValue({ portal_url: "https://billing.stripe.com/session/abc" });
    const originalLocation = window.location;
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...originalLocation, href: "http://localhost/settings/plan" },
    });

    const user = userEvent.setup();
    renderWithProviders(<ManageBillingButton />);

    await user.click(screen.getByRole("button", { name: "Manage billing" }));

    await waitFor(() =>
      expect(window.location.href).toBe("https://billing.stripe.com/session/abc")
    );
    const call = apiFetchMock.mock.calls[0];
    expect(call[0]).toBe("/organizations/org-1/billing/portal");
    const body = JSON.parse((call[1] as RequestInit).body as string);
    expect(body.return_url).toBe("http://localhost/settings/plan");

    Object.defineProperty(window, "location", { configurable: true, value: originalLocation });
  });

  it("shows a 'choose a plan first' message on a 404 response", async () => {
    loginWithBillingManage();
    apiFetchMock.mockRejectedValue(new ApiError("Not Found", 404, { detail: "no customer" }));

    const user = userEvent.setup();
    renderWithProviders(<ManageBillingButton />);

    await user.click(screen.getByRole("button", { name: "Manage billing" }));

    expect(
      await screen.findByText("Choose a plan first to set up billing.")
    ).toBeInTheDocument();
  });

  it("shows a generic error message on a non-404 failure", async () => {
    loginWithBillingManage();
    apiFetchMock.mockRejectedValue(new ApiError("Internal Server Error", 500));

    const user = userEvent.setup();
    renderWithProviders(<ManageBillingButton />);

    await user.click(screen.getByRole("button", { name: "Manage billing" }));

    expect(await screen.findByText("Internal Server Error")).toBeInTheDocument();
  });
});
