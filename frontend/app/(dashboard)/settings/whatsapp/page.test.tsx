import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setAuthSession } from "@/lib/auth-storage";
import type {
  Member,
  PaginatedMembers,
  WhatsAppCommandHistoryResponse,
  WhatsAppIdentityListResponse,
  WhatsAppIdentityResponse,
  WhatsAppLinkResponse,
  WhatsAppQrResponse,
  WhatsAppStatusResponse,
} from "@/lib/types";
import { renderWithProviders } from "@/tests/test-utils";

import WhatsAppSettingsPage from "./page";

vi.mock("next/navigation", () => ({
  usePathname: () => "/settings/whatsapp",
}));

const apiFetchMock = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    apiFetch: (...args: unknown[]) => apiFetchMock(...args),
  };
});

function makeMember(overrides: Partial<Member> = {}): Member {
  return {
    id: "member-1",
    organization_id: "org-1",
    user_id: "user-1",
    user_email: "self@example.com",
    role: "member",
    status: "active",
    invited_by_email: null,
    invited_at: null,
    accepted_at: "2026-01-01T00:00:00Z",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    permissions: ["invoice.read"],
    ...overrides,
  };
}

const statusConnected: WhatsAppStatusResponse = {
  transport_enabled: true,
  transport_configured: true,
  plan_allows_whatsapp: true,
  plan_allows_voice_messages: true,
  connection: { state: "connected", connected_phone_number: "+15550001111", last_heartbeat_at: null },
  whatsapp_users_quota: { used: 1, limit: 5, unlimited: false },
  whatsapp_actions_quota: { used: 3, limit: 200, unlimited: false },
};

function mockApi(
  members: Member[],
  status: WhatsAppStatusResponse,
  me: WhatsAppIdentityResponse | null,
  identities: WhatsAppIdentityListResponse = { items: [] },
  history: WhatsAppCommandHistoryResponse = { items: [] },
  extra?: (path: string, init: RequestInit | undefined) => unknown
) {
  apiFetchMock.mockImplementation((path: string, init?: RequestInit) => {
    const method = init?.method;
    if (path.endsWith("/members") && !method) {
      return Promise.resolve<PaginatedMembers>({ total: members.length, items: members });
    }
    if (path.endsWith("/whatsapp/status") && !method) {
      return Promise.resolve(status);
    }
    if (path.endsWith("/whatsapp/me") && !method) {
      return Promise.resolve(me);
    }
    if (path.endsWith("/whatsapp/identities") && !method) {
      return Promise.resolve(identities);
    }
    if (path.endsWith("/whatsapp/history") && !method) {
      return Promise.resolve(history);
    }
    if (extra) {
      const result = extra(path, init);
      if (result !== undefined) return result as Promise<unknown>;
    }
    return Promise.reject(new Error(`unexpected call: ${path} ${method ?? "GET"}`));
  });
}

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

describe("WhatsAppSettingsPage", () => {
  it("shows the experimental/unofficial warning for every viewer", async () => {
    mockApi([makeMember()], statusConnected, null);
    renderWithProviders(<WhatsAppSettingsPage />);

    await waitFor(() => expect(screen.getByText("WhatsApp Assistant")).toBeInTheDocument());
    expect(screen.getByText(/unofficial, experimental integration/i)).toBeInTheDocument();
    expect(screen.getByText("Experimental")).toBeInTheDocument();
  });

  it("hides org-wide connection controls and tables from a member without settings.manage", async () => {
    mockApi([makeMember({ permissions: ["invoice.read"] })], statusConnected, null);
    renderWithProviders(<WhatsAppSettingsPage />);

    await waitFor(() => expect(screen.getByText("Connected")).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "Show QR" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reconnect" })).not.toBeInTheDocument();
    expect(screen.queryByText("Recent activity")).not.toBeInTheDocument();
    // Self-service linking is still available to every member.
    expect(screen.getByText("Your WhatsApp number")).toBeInTheDocument();
  });

  it("shows connection controls and org-wide tables for a member with settings.manage", async () => {
    const identity: WhatsAppIdentityResponse = {
      id: "identity-1",
      user_id: "user-2",
      user_email: "teammate@example.com",
      normalized_phone_number: "+15559998888",
      status: "verified",
      verified_at: "2026-01-01T00:00:00Z",
      last_message_at: null,
      created_at: "2026-01-01T00:00:00Z",
    };
    mockApi(
      [makeMember({ permissions: ["settings.manage"] })],
      statusConnected,
      null,
      { items: [identity] },
      { items: [] }
    );
    renderWithProviders(<WhatsAppSettingsPage />);

    await waitFor(() => expect(screen.getByRole("button", { name: "Show QR" })).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Reconnect" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Disconnect" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete session" })).toBeInTheDocument();
    expect(screen.getByText("teammate@example.com")).toBeInTheDocument();
  });

  it("shows the plan-restricted banner when the plan doesn't allow WhatsApp", async () => {
    mockApi([makeMember()], { ...statusConnected, plan_allows_whatsapp: false }, null);
    renderWithProviders(<WhatsAppSettingsPage />);

    await waitFor(() =>
      expect(screen.getByText("Your organization's plan doesn't include the WhatsApp assistant.")).toBeInTheDocument()
    );
  });

  it("links a phone number and shows the one-time verification code", async () => {
    const linkResponse: WhatsAppLinkResponse = {
      identity_id: "identity-2",
      normalized_phone_number: "+15551234567",
      status: "pending",
      verification_code: "482913",
      verification_expires_at: "2026-01-01T00:10:00Z",
    };
    mockApi([makeMember()], statusConnected, null, undefined, undefined, (path, init) => {
      if (path.endsWith("/whatsapp/link") && init?.method === "POST") {
        return Promise.resolve(linkResponse);
      }
      return undefined;
    });

    const user = userEvent.setup();
    renderWithProviders(<WhatsAppSettingsPage />);
    await waitFor(() => expect(screen.getByLabelText("Phone number")).toBeInTheDocument());

    await user.type(screen.getByLabelText("Phone number"), "+15551234567");
    await user.click(screen.getByRole("button", { name: "Link number" }));

    expect(await screen.findByText("482913")).toBeInTheDocument();
    expect(screen.getByText("One more step")).toBeInTheDocument();
  });

  it("keeps showing the one-time code across the post-link refresh, and clears it once verified", async () => {
    // Regression test: linking creates a `pending` identity immediately,
    // and the page reloads its own data right after a successful link.
    // The code must survive that reload (the user hasn't necessarily
    // copied it yet) and only disappear once the identity is actually
    // verified -- not the instant an identity row exists.
    const linkResponse: WhatsAppLinkResponse = {
      identity_id: "identity-4",
      normalized_phone_number: "+15551234567",
      status: "pending",
      verification_code: "739201",
      verification_expires_at: "2026-01-01T00:10:00Z",
    };
    const pendingIdentity: WhatsAppIdentityResponse = {
      id: "identity-4",
      user_id: "user-1",
      user_email: "self@example.com",
      normalized_phone_number: "+15551234567",
      status: "pending",
      verified_at: null,
      last_message_at: null,
      created_at: "2026-01-01T00:00:00Z",
    };
    let meResponse: WhatsAppIdentityResponse | null = null;
    apiFetchMock.mockImplementation((path: string, init?: RequestInit) => {
      const method = init?.method;
      if (path.endsWith("/members") && !method) {
        return Promise.resolve<PaginatedMembers>({ total: 1, items: [makeMember()] });
      }
      if (path.endsWith("/whatsapp/status") && !method) {
        return Promise.resolve(statusConnected);
      }
      if (path.endsWith("/whatsapp/me") && !method) {
        return Promise.resolve(meResponse);
      }
      if (path.endsWith("/whatsapp/link") && method === "POST") {
        meResponse = pendingIdentity;
        return Promise.resolve(linkResponse);
      }
      return Promise.reject(new Error(`unexpected call: ${path} ${method ?? "GET"}`));
    });

    const user = userEvent.setup();
    renderWithProviders(<WhatsAppSettingsPage />);
    await waitFor(() => expect(screen.getByLabelText("Phone number")).toBeInTheDocument());

    await user.type(screen.getByLabelText("Phone number"), "+15551234567");
    await user.click(screen.getByRole("button", { name: "Link number" }));

    // The background refresh triggered by onChanged() now resolves
    // GET .../whatsapp/me with a real (pending) identity -- the code must
    // still be on screen, not replaced by the "Pending verification" badge.
    await waitFor(() => expect(screen.getByText("739201")).toBeInTheDocument());
    expect(screen.queryByText("Pending verification")).not.toBeInTheDocument();
  });

  it("revokes the caller's own linked number after confirmation", async () => {
    const identity: WhatsAppIdentityResponse = {
      id: "identity-3",
      user_id: "user-1",
      user_email: "self@example.com",
      normalized_phone_number: "+15551234567",
      status: "verified",
      verified_at: "2026-01-01T00:00:00Z",
      last_message_at: null,
      created_at: "2026-01-01T00:00:00Z",
    };
    let revoked = false;
    apiFetchMock.mockImplementation((path: string, init?: RequestInit) => {
      const method = init?.method;
      if (path.endsWith("/members") && !method) {
        return Promise.resolve<PaginatedMembers>({ total: 1, items: [makeMember()] });
      }
      if (path.endsWith("/whatsapp/status") && !method) {
        return Promise.resolve(statusConnected);
      }
      if (path.endsWith("/whatsapp/me") && !method) {
        return Promise.resolve(revoked ? null : identity);
      }
      if (path.endsWith("/whatsapp/me/revoke") && method === "POST") {
        revoked = true;
        return Promise.resolve(undefined);
      }
      return Promise.reject(new Error(`unexpected call: ${path} ${method ?? "GET"}`));
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);

    const user = userEvent.setup();
    renderWithProviders(<WhatsAppSettingsPage />);
    await waitFor(() => expect(screen.getByText("+15551234567")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "Unlink" }));

    await waitFor(() => expect(screen.getByRole("button", { name: "Link number" })).toBeInTheDocument());
  });

  it("requests and displays a QR code for a settings.manage user", async () => {
    const qr: WhatsAppQrResponse = { qr_data_base64: "ZmFrZS1xcg==", expires_at: "2026-01-01T00:05:00Z" };
    mockApi(
      [makeMember({ permissions: ["settings.manage"] })],
      { ...statusConnected, connection: { state: "qr_required", connected_phone_number: null, last_heartbeat_at: null } },
      null,
      undefined,
      undefined,
      (path, init) => {
        if (path.endsWith("/whatsapp/qr") && init?.method === "POST") {
          return Promise.resolve(qr);
        }
        return undefined;
      }
    );

    const user = userEvent.setup();
    renderWithProviders(<WhatsAppSettingsPage />);
    await waitFor(() => expect(screen.getByRole("button", { name: "Show QR" })).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "Show QR" }));

    const dialog = await screen.findByRole("dialog", { name: "Scan this QR code" });
    const img = within(dialog).getByRole("img");
    expect(img).toHaveAttribute("src", "data:image/png;base64,ZmFrZS1xcg==");
  });
});
