import { beforeEach, describe, expect, it, vi } from "vitest";

import { setAuthSession } from "@/lib/auth-storage";
import type { MeResponse } from "@/lib/types";
import { renderWithProviders, screen, waitFor } from "@/tests/test-utils";

import { PlatformAdminShell } from "./PlatformAdminShell";

const routerReplace = vi.fn();

vi.mock("next/navigation", () => ({
  usePathname: () => "/admin",
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

const meWithNoOrganizations: MeResponse = {
  user: { id: "admin-1", email: "root@example.com", email_verified: true, platform_role: "super_admin" },
  organizations: [],
};

const meWithOneOrganization: MeResponse = {
  user: { id: "admin-1", email: "root@example.com", email_verified: true, platform_role: "super_admin" },
  organizations: [
    { id: "org-1", name: "Acme Inc", currency_code: "USD", language: "en", permissions: [], status: "active" },
  ],
};

beforeEach(() => {
  window.localStorage.clear();
  routerReplace.mockClear();
  apiFetchMock.mockReset();
});

describe("PlatformAdminShell", () => {
  it("redirects to /login when there is no token at all", async () => {
    renderWithProviders(<PlatformAdminShell>content</PlatformAdminShell>);

    await waitFor(() => expect(routerReplace).toHaveBeenCalledWith("/login"));
    expect(apiFetchMock).not.toHaveBeenCalled();
  });

  it("redirects an authenticated user with no platform role to /dashboard", async () => {
    setAuthSession({ token: "test-token", apiBaseUrl: "http://localhost:8000", organizationId: "org-1" });
    // No platformRole passed -- this account is an ordinary organization user.

    renderWithProviders(<PlatformAdminShell>content</PlatformAdminShell>);

    await waitFor(() => expect(routerReplace).toHaveBeenCalledWith("/dashboard"));
    expect(apiFetchMock).not.toHaveBeenCalled();
  });

  it("renders the admin nav for a platform admin with zero organizations", async () => {
    setAuthSession({ token: "test-token", apiBaseUrl: "http://localhost:8000", platformRole: "super_admin" });
    apiFetchMock.mockResolvedValue(meWithNoOrganizations);

    renderWithProviders(<PlatformAdminShell>content</PlatformAdminShell>);

    await waitFor(() => expect(screen.getAllByText("Organizations").length).toBeGreaterThan(0));
    expect(routerReplace).not.toHaveBeenCalled();
    expect(screen.queryByText("Return to organization")).not.toBeInTheDocument();
  });

  it("shows an Audit Log nav link", async () => {
    setAuthSession({ token: "test-token", apiBaseUrl: "http://localhost:8000", platformRole: "super_admin" });
    apiFetchMock.mockResolvedValue(meWithNoOrganizations);

    renderWithProviders(<PlatformAdminShell>content</PlatformAdminShell>);

    await waitFor(() => expect(screen.getAllByText("Audit Log").length).toBeGreaterThan(0));
    const links = screen.getAllByRole("link", { name: "Audit Log" });
    expect(links.some((link) => link.getAttribute("href") === "/admin/audit-log")).toBe(true);
  });

  it("shows a return-to-organization link when the platform admin also has an organization", async () => {
    setAuthSession({
      token: "test-token",
      apiBaseUrl: "http://localhost:8000",
      organizationId: "org-1",
      platformRole: "super_admin",
    });
    apiFetchMock.mockResolvedValue(meWithOneOrganization);

    renderWithProviders(<PlatformAdminShell>content</PlatformAdminShell>);

    await waitFor(() => expect(screen.getAllByText("Return to organization").length).toBeGreaterThan(0));
  });

  it("redirects to /dashboard if the platform role was revoked server-side", async () => {
    setAuthSession({ token: "test-token", apiBaseUrl: "http://localhost:8000", platformRole: "super_admin" });
    apiFetchMock.mockResolvedValue({
      user: { id: "admin-1", email: "root@example.com", email_verified: true, platform_role: null },
      organizations: [],
    });

    renderWithProviders(<PlatformAdminShell>content</PlatformAdminShell>);

    await waitFor(() => expect(routerReplace).toHaveBeenCalledWith("/dashboard"));
  });

  it("does not mount the child page (or fetch its data) until /auth/me confirms a live platform role", async () => {
    setAuthSession({ token: "test-token", apiBaseUrl: "http://localhost:8000", platformRole: "super_admin" });
    const childFetch = vi.fn();
    let resolveMe: (value: MeResponse) => void;
    apiFetchMock.mockImplementation(
      () => new Promise<MeResponse>((resolve) => { resolveMe = resolve; })
    );

    function ProbeChild() {
      childFetch();
      return <div>admin page content</div>;
    }

    renderWithProviders(
      <PlatformAdminShell>
        <ProbeChild />
      </PlatformAdminShell>
    );

    // While /auth/me is still pending, a neutral loading state is shown --
    // never the cached platform_role treated as sufficient on its own --
    // and the child page component (and therefore any /admin/* fetch it
    // would make on mount) must not exist in the tree at all.
    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.queryByText("admin page content")).not.toBeInTheDocument();
    expect(childFetch).not.toHaveBeenCalled();

    resolveMe!(meWithNoOrganizations);

    await waitFor(() => expect(screen.getByText("admin page content")).toBeInTheDocument());
    expect(childFetch).toHaveBeenCalledTimes(1);
  });
});
