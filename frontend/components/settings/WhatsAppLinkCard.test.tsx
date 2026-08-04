import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setAuthSession } from "@/lib/auth-storage";
import type { WhatsAppIdentityResponse, WhatsAppLinkResponse } from "@/lib/types";
import { renderWithProviders } from "@/tests/test-utils";

import { WhatsAppLinkCard } from "./WhatsAppLinkCard";

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
  setAuthSession({
    token: "test-token",
    apiBaseUrl: "http://localhost:8000",
    organizationId: "org-1",
    userEmail: "self@example.com",
  });
});

const pendingIdentity: WhatsAppIdentityResponse = {
  id: "identity-1",
  user_id: "user-1",
  user_email: "self@example.com",
  normalized_phone_number: "+15551234567",
  status: "pending",
  verified_at: null,
  last_message_at: null,
  created_at: "2026-01-01T00:00:00Z",
};

describe("WhatsAppLinkCard", () => {
  it("keeps the one-time code on screen once the parent's own identity prop arrives as pending", async () => {
    const linkResponse: WhatsAppLinkResponse = {
      identity_id: "identity-1",
      normalized_phone_number: "+15551234567",
      status: "pending",
      verification_code: "482913",
      verification_expires_at: "2026-01-01T00:10:00Z",
    };
    apiFetchMock.mockImplementation((path: string, init?: RequestInit) => {
      if (path.endsWith("/whatsapp/link") && init?.method === "POST") {
        return Promise.resolve(linkResponse);
      }
      return Promise.reject(new Error(`unexpected call: ${path}`));
    });

    const user = userEvent.setup();
    const { rerender } = renderWithProviders(
      <WhatsAppLinkCard identity={null} canUseWhatsapp onChanged={() => {}} />
    );

    await user.type(screen.getByLabelText("Phone number"), "+15551234567");
    await user.click(screen.getByRole("button", { name: "Link number" }));
    await waitFor(() => expect(screen.getByText("482913")).toBeInTheDocument());

    // Simulate the parent's background refresh handing back the now-real
    // (still pending) identity -- the code must stay the priority view.
    rerender(<WhatsAppLinkCard identity={pendingIdentity} canUseWhatsapp onChanged={() => {}} />);
    expect(screen.getByText("482913")).toBeInTheDocument();
    expect(screen.queryByText("Pending verification")).not.toBeInTheDocument();

    // Once the identity is actually verified, the code view gives way to
    // the normal linked-number badge.
    rerender(
      <WhatsAppLinkCard
        identity={{ ...pendingIdentity, status: "verified", verified_at: "2026-01-01T00:05:00Z" }}
        canUseWhatsapp
        onChanged={() => {}}
      />
    );
    expect(screen.queryByText("482913")).not.toBeInTheDocument();
    expect(screen.getByText("Verified")).toBeInTheDocument();
  });

  it("shows the badge (not a form) for an already-pending identity from a previous session, with no code to show", () => {
    renderWithProviders(<WhatsAppLinkCard identity={pendingIdentity} canUseWhatsapp onChanged={() => {}} />);
    expect(screen.getByText("Pending verification")).toBeInTheDocument();
    expect(screen.queryByLabelText("Phone number")).not.toBeInTheDocument();
  });

  it("lets the user cancel a pending link before it's verified", async () => {
    const linkResponse: WhatsAppLinkResponse = {
      identity_id: "identity-1",
      normalized_phone_number: "+15551234567",
      status: "pending",
      verification_code: "482913",
      verification_expires_at: "2026-01-01T00:10:00Z",
    };
    apiFetchMock.mockImplementation((path: string, init?: RequestInit) => {
      if (path.endsWith("/whatsapp/link") && init?.method === "POST") {
        return Promise.resolve(linkResponse);
      }
      if (path.endsWith("/whatsapp/me/revoke") && init?.method === "POST") {
        return Promise.resolve(undefined);
      }
      return Promise.reject(new Error(`unexpected call: ${path}`));
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);

    const user = userEvent.setup();
    renderWithProviders(<WhatsAppLinkCard identity={null} canUseWhatsapp onChanged={() => {}} />);

    await user.type(screen.getByLabelText("Phone number"), "+15551234567");
    await user.click(screen.getByRole("button", { name: "Link number" }));
    await waitFor(() => expect(screen.getByText("482913")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "Unlink" }));
    expect(apiFetchMock).toHaveBeenCalledWith("/organizations/org-1/whatsapp/me/revoke", { method: "POST" });
  });
});
