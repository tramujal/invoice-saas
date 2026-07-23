import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setAuthSession } from "@/lib/auth-storage";
import type { Member, PaginatedInvitations, PaginatedMembers } from "@/lib/types";
import { renderWithProviders, screen, waitFor, within } from "@/tests/test-utils";

import TeamPage from "./page";

/** Grant ownership / Remove now live inside the shared RowActionsMenu (see
 * components/ui/RowActionsMenu.test.tsx for its own open/close/keyboard/
 * disabled behavior, not duplicated here) -- a row's menu items only exist
 * in the DOM once its "More actions" trigger has been opened, and the
 * opened panel portals to document.body rather than staying inside the
 * row's <tr>, so callers must locate the trigger scoped to the row, click
 * it, then query the menu items globally via `screen`. */
async function openRowMenu(rowAccessibleText: string) {
  const row = screen.getByText(rowAccessibleText).closest("tr");
  if (!row) throw new Error(`row containing "${rowAccessibleText}" not found`);
  const user = userEvent.setup();
  await user.click(within(row).getByRole("button", { name: "More actions" }));
}

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
    // No actions column at all for a viewer -- not even a "More actions"
    // trigger to open, since canManageMembers gates the whole <td>.
    expect(screen.queryByRole("button", { name: "More actions" })).not.toBeInTheDocument();
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

    // The admin row (not the owner's own row, which never offers itself
    // grant-ownership) is where an owner's grant-ownership action lives.
    await openRowMenu("admin@example.com");
    expect(screen.getByRole("menuitem", { name: "Grant ownership" })).toBeInTheDocument();
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

    // members.manage alone still opens the menu (Remove is available), but
    // without organization.manage the grant-ownership item must be absent.
    await openRowMenu("self@example.com");
    expect(screen.getByRole("menuitem", { name: "Remove" })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "Grant ownership" })).not.toBeInTheDocument();
  });

  it("hides management controls immediately after self-demotion, with no reload needed", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    const adminSelf = makeMember({
      id: "self-id",
      user_email: "self@example.com",
      role: "admin",
      permissions: ["members.manage"],
    });
    const viewerSelf = makeMember({
      id: "self-id",
      user_email: "self@example.com",
      role: "viewer",
      permissions: [],
    });
    const user = userEvent.setup();

    let membersLoadCount = 0;
    apiFetchMock.mockImplementation((path: string, init?: RequestInit) => {
      if (path.includes("/invitations")) return Promise.resolve(emptyInvitations);
      if (path.includes("/members/self-id") && init?.method === "PATCH") {
        return Promise.resolve(viewerSelf);
      }
      if (path.includes("/members")) {
        membersLoadCount += 1;
        const items = membersLoadCount === 1 ? [adminSelf] : [viewerSelf];
        return Promise.resolve({ total: 1, items } satisfies PaginatedMembers);
      }
      return Promise.reject(new Error(`unexpected call: ${path}`));
    });

    renderWithProviders(<TeamPage />);
    await waitFor(() => expect(screen.getByRole("button", { name: "Send invitation" })).toBeInTheDocument());

    const roleSelect = screen.getByRole("combobox", { name: "Change role for self@example.com" });
    await user.selectOptions(roleSelect, "viewer");

    // No page reload anywhere in this flow -- the reduced permission set
    // (canManageMembers/canGrantOwnership) is recomputed purely from the
    // freshly-reloaded `self` row returned by the second GET /members.
    await waitFor(() => expect(screen.queryByRole("button", { name: "Send invitation" })).not.toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "More actions" })).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();

    confirmSpy.mockRestore();
  });

  it("admin sees no role select or actions menu for another admin's row -- only for self and lower-ranked members", async () => {
    const adminSelf = makeMember({
      id: "self-id",
      user_email: "self@example.com",
      role: "admin",
      permissions: ["members.manage"],
    });
    const otherAdmin = makeMember({
      id: "other-admin-id",
      user_email: "other-admin@example.com",
      role: "admin",
      permissions: ["members.manage"],
    });
    const viewerMember = makeMember({
      id: "viewer-id",
      user_email: "viewer@example.com",
      role: "viewer",
      permissions: [],
    });
    const membersResponse: PaginatedMembers = { total: 3, items: [adminSelf, otherAdmin, viewerMember] };
    apiFetchMock.mockImplementation((path: string) => {
      if (path.includes("/invitations")) return Promise.resolve(emptyInvitations);
      if (path.includes("/members")) return Promise.resolve(membersResponse);
      return Promise.reject(new Error(`unexpected call: ${path}`));
    });

    renderWithProviders(<TeamPage />);
    await waitFor(() => expect(screen.getByText("other-admin@example.com")).toBeInTheDocument());

    const otherAdminRow = screen.getByText("other-admin@example.com").closest("tr");
    expect(otherAdminRow).not.toBeNull();
    expect(within(otherAdminRow as HTMLElement).queryByRole("combobox")).not.toBeInTheDocument();
    expect(within(otherAdminRow as HTMLElement).queryByRole("button", { name: "More actions" })).not.toBeInTheDocument();

    // The viewer's row (lower rank) still gets full controls.
    const viewerRow = screen.getByText("viewer@example.com").closest("tr");
    expect(within(viewerRow as HTMLElement).getByRole("combobox")).toBeInTheDocument();
    expect(within(viewerRow as HTMLElement).getByRole("button", { name: "More actions" })).toBeInTheDocument();

    // Self's own row still gets controls (self-modification is exempt).
    const selfRow = screen.getByText("self@example.com").closest("tr");
    expect(within(selfRow as HTMLElement).getByRole("button", { name: "More actions" })).toBeInTheDocument();
  });
});
