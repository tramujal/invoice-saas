import { beforeEach, describe, expect, it, vi } from "vitest";

import { setAuthSession } from "@/lib/auth-storage";
import type { Member, PaginatedInvitations, PaginatedMembers } from "@/lib/types";
import { renderWithProviders, screen, waitFor } from "@/tests/test-utils";

import TeamPage from "./page";

vi.mock("next/navigation", () => ({
  usePathname: () => "/settings/team",
}));

const apiFetchMock = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    apiFetch: (...args: unknown[]) => apiFetchMock(...args),
  };
});

function makeMember(overrides: Partial<Member>): Member {
  return {
    id: "member-1",
    organization_id: "org-1",
    user_id: "user-1",
    user_email: "self@example.com",
    role: "member",
    status: "active",
    invited_by_email: null,
    invited_at: null,
    accepted_at: new Date().toISOString(),
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    permissions: [],
    ...overrides,
  };
}

const emptyInvitations: PaginatedInvitations = { total: 0, items: [] };

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

describe("Team page permission-gated rendering", () => {
  it("viewer sees no invite form and no per-row action controls", async () => {
    const viewerSelf = makeMember({
      id: "self-id",
      user_email: "self@example.com",
      role: "viewer",
      permissions: ["customer.read", "product.read"],
    });
    const membersResponse: PaginatedMembers = { total: 1, items: [viewerSelf] };
    apiFetchMock.mockImplementation((path: string) => {
      if (path.includes("/members")) return Promise.resolve(membersResponse);
      return Promise.reject(new Error(`unexpected call: ${path}`));
    });

    renderWithProviders(<TeamPage />);
    await waitFor(() => expect(screen.getByText("self@example.com")).toBeInTheDocument());

    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /remove/i })).not.toBeInTheDocument();
    // A viewer's own load() never even requests the invitations endpoint.
    expect(apiFetchMock).not.toHaveBeenCalledWith(expect.stringContaining("/invitations"));
  });

  it("owner sees the invite form, role select, and grant-ownership button", async () => {
    const ownerSelf = makeMember({
      id: "self-id",
      user_email: "self@example.com",
      role: "owner",
      permissions: ["members.manage", "organization.manage"],
    });
    const otherAdmin = makeMember({
      id: "other-id",
      user_email: "admin@example.com",
      role: "admin",
      permissions: ["members.manage"],
    });
    const membersResponse: PaginatedMembers = { total: 2, items: [ownerSelf, otherAdmin] };
    apiFetchMock.mockImplementation((path: string) => {
      if (path.includes("/invitations")) return Promise.resolve(emptyInvitations);
      if (path.includes("/members")) return Promise.resolve(membersResponse);
      return Promise.reject(new Error(`unexpected call: ${path}`));
    });

    renderWithProviders(<TeamPage />);
    await waitFor(() => expect(screen.getByText("admin@example.com")).toBeInTheDocument());

    expect(screen.getByRole("textbox")).toBeInTheDocument();
    expect(screen.getAllByRole("combobox").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Grant ownership" })).toBeInTheDocument();
  });

  it("admin (without organization.manage) sees role controls but no grant-ownership button", async () => {
    const adminSelf = makeMember({
      id: "self-id",
      user_email: "self@example.com",
      role: "admin",
      permissions: ["members.manage"],
    });
    const membersResponse: PaginatedMembers = { total: 1, items: [adminSelf] };
    apiFetchMock.mockImplementation((path: string) => {
      if (path.includes("/invitations")) return Promise.resolve(emptyInvitations);
      if (path.includes("/members")) return Promise.resolve(membersResponse);
      return Promise.reject(new Error(`unexpected call: ${path}`));
    });

    renderWithProviders(<TeamPage />);
    await waitFor(() => expect(screen.getByText("self@example.com")).toBeInTheDocument());

    expect(screen.getAllByRole("combobox").length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: "Grant ownership" })).not.toBeInTheDocument();
  });
});
