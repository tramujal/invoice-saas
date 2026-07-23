import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setAuthSession } from "@/lib/auth-storage";
import type { MeResponse } from "@/lib/types";
import { renderWithProviders, screen, waitFor } from "@/tests/test-utils";

import { AppShell } from "./AppShell";

const routerReplace = vi.fn();

vi.mock("next/navigation", () => ({
  usePathname: () => "/dashboard",
  useRouter: () => ({ replace: routerReplace, push: vi.fn() }),
}));

const apiFetchMock = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    apiFetch: (...args: unknown[]) => apiFetchMock(...args),
  };
});

const meResponse: MeResponse = {
  user: { id: "user-1", email: "owner@example.com", email_verified: true, platform_role: null },
  organizations: [
    {
      id: "org-1",
      name: "Acme Inc",
      currency_code: "USD",
      language: "en",
      permissions: ["invoice.send", "quote.send"],
      status: "active",
    },
  ],
};

beforeEach(() => {
  window.localStorage.clear();
  routerReplace.mockClear();
  apiFetchMock.mockReset();
  apiFetchMock.mockResolvedValue(meResponse);
  setAuthSession({
    token: "test-token",
    apiBaseUrl: "http://localhost:8000",
    organizationId: "org-1",
    organizationName: "Acme Inc",
    emailVerified: true,
  });
});

describe("AppShell mobile nav", () => {
  it("opens the off-canvas panel when the hamburger button is clicked", async () => {
    const user = userEvent.setup();
    renderWithProviders(<AppShell>content</AppShell>);
    await waitFor(() => expect(apiFetchMock).toHaveBeenCalled());

    const openButton = screen.getByRole("button", { name: "Open menu" });
    await user.click(openButton);

    const dialog = document.querySelector("dialog") as HTMLDialogElement;
    expect(dialog.hasAttribute("open")).toBe(true);
  });

  it("closes the panel and returns focus to the hamburger button", async () => {
    const user = userEvent.setup();
    renderWithProviders(<AppShell>content</AppShell>);
    await waitFor(() => expect(apiFetchMock).toHaveBeenCalled());

    const openButton = screen.getByRole("button", { name: "Open menu" });
    await user.click(openButton);

    const closeButton = screen.getByRole("button", { name: "Close menu" });
    await user.click(closeButton);

    const dialog = document.querySelector("dialog") as HTMLDialogElement;
    expect(dialog.hasAttribute("open")).toBe(false);
    expect(openButton).toHaveFocus();
  });

  it("closes the panel when a nav link inside it is clicked", async () => {
    const user = userEvent.setup();
    renderWithProviders(<AppShell>content</AppShell>);
    await waitFor(() => expect(apiFetchMock).toHaveBeenCalled());

    await user.click(screen.getByRole("button", { name: "Open menu" }));
    const dialog = document.querySelector("dialog") as HTMLDialogElement;
    expect(dialog.hasAttribute("open")).toBe(true);

    // Two "Invoices" links exist (desktop sidebar + mobile panel) --
    // querying scoped to the open dialog picks the mobile one.
    const invoicesLinkInDialog = Array.from(dialog.querySelectorAll("a")).find(
      (a) => a.textContent === "Invoices"
    );
    expect(invoicesLinkInDialog).toBeTruthy();
    await user.click(invoicesLinkInDialog!);

    expect(dialog.hasAttribute("open")).toBe(false);
  });

  it("redirects to /login when not authenticated", async () => {
    window.localStorage.clear();
    renderWithProviders(<AppShell>content</AppShell>);

    await waitFor(() => expect(routerReplace).toHaveBeenCalledWith("/login"));
  });
});

describe("AppShell platform admin entry link", () => {
  it("is hidden when the user has no platform role", async () => {
    renderWithProviders(<AppShell>content</AppShell>);
    await waitFor(() => expect(apiFetchMock).toHaveBeenCalled());

    expect(screen.queryByText("Platform Admin")).not.toBeInTheDocument();
  });

  it("is shown once /auth/me reports a platform role", async () => {
    apiFetchMock.mockResolvedValue({
      ...meResponse,
      user: { ...meResponse.user, platform_role: "super_admin" },
    });

    renderWithProviders(<AppShell>content</AppShell>);

    await waitFor(() => expect(screen.getAllByText("Platform Admin").length).toBeGreaterThan(0));
  });
});

describe("AppShell active-organization fallback", () => {
  it("switches to another organization when the cached active org is missing from /auth/me (self-removal)", async () => {
    const assignSpy = vi.fn();
    const originalLocation = window.location;
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...originalLocation, assign: assignSpy },
    });

    const otherOrg = {
      id: "org-2",
      name: "Other Org",
      currency_code: "EUR",
      language: "es",
      permissions: ["invoice.send"],
      status: "active" as const,
    };
    apiFetchMock.mockResolvedValue({
      user: meResponse.user,
      organizations: [otherOrg],
    });

    renderWithProviders(<AppShell>content</AppShell>);

    await waitFor(() => expect(assignSpy).toHaveBeenCalledWith("/dashboard"));
    expect(window.localStorage.getItem("invoicing_organization_id")).toBe("org-2");

    Object.defineProperty(window, "location", { configurable: true, value: originalLocation });
  });

  it("clears the session and redirects to /login when no organizations remain", async () => {
    apiFetchMock.mockResolvedValue({
      user: meResponse.user,
      organizations: [],
    });

    renderWithProviders(<AppShell>content</AppShell>);

    await waitFor(() => expect(routerReplace).toHaveBeenCalledWith("/login"));
    expect(window.localStorage.getItem("invoicing_auth_token")).toBeNull();
  });
});

describe("AppShell suspended-organization notice", () => {
  it("renders children normally when the active organization is active", async () => {
    renderWithProviders(<AppShell>dashboard content</AppShell>);

    await waitFor(() => expect(screen.getByText("dashboard content")).toBeInTheDocument());
    expect(screen.queryByText("This organization has been suspended")).not.toBeInTheDocument();
  });

  it("replaces children with a blocking notice when the active organization is suspended", async () => {
    apiFetchMock.mockResolvedValue({
      ...meResponse,
      organizations: [{ ...meResponse.organizations[0], status: "suspended" }],
    });

    renderWithProviders(<AppShell>dashboard content</AppShell>);

    await waitFor(() =>
      expect(screen.getByText("This organization has been suspended")).toBeInTheDocument()
    );
    expect(screen.queryByText("dashboard content")).not.toBeInTheDocument();
  });
});
