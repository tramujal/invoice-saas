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
  user: { id: "user-1", email: "owner@example.com", email_verified: true },
  organizations: [
    {
      id: "org-1",
      name: "Acme Inc",
      currency_code: "USD",
      language: "en",
      permissions: ["invoice.send", "quote.send"],
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
