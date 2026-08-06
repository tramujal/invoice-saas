import { beforeEach, describe, expect, it, vi } from "vitest";

import { setAuthSession } from "@/lib/auth-storage";
import type { MeResponse, OrganizationProfile } from "@/lib/types";
import { renderWithProviders, screen, waitFor } from "@/tests/test-utils";

import SettingsPage from "./page";

vi.mock("next/navigation", () => ({
  usePathname: () => "/settings",
}));

const apiFetchMock = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    apiFetch: (...args: unknown[]) => apiFetchMock(...args),
  };
});

const PROFILE: OrganizationProfile = {
  id: "org-1",
  name: "Acme Inc",
  business_name: null,
  tax_id: null,
  address: null,
  phone: null,
  email: null,
  logo_url: null,
  language: "en",
  currency_code: "USD",
  tax_label: "tax",
  timezone: "UTC",
  reminders_enabled: false,
  reminder_before_due_days: [],
  reminder_on_due_date: false,
  reminder_after_due_days: [],
  quote_reminders_enabled: false,
  quote_reminder_before_expiry_days: [],
};

function meResponse(overrides: Partial<MeResponse["user"]> = {}): MeResponse {
  return {
    user: {
      id: "user-1",
      email: "owner@example.com",
      email_verified: true,
      platform_role: null,
      has_google_account: false,
      password_set: true,
      ...overrides,
    },
    organizations: [],
  };
}

function mockEndpoints(me: MeResponse, disconnect?: () => Promise<unknown>) {
  apiFetchMock.mockImplementation((path: string, init?: RequestInit) => {
    if (path === "/auth/me") return Promise.resolve(me);
    if (path.endsWith("/auth/google/disconnect") && init?.method === "POST") {
      return disconnect ? disconnect() : Promise.resolve({ message: "ok" });
    }
    if (path.startsWith("/organizations/")) return Promise.resolve(PROFILE);
    return Promise.reject(new Error(`unexpected call: ${path}`));
  });
}

beforeEach(() => {
  window.localStorage.clear();
  apiFetchMock.mockReset();
  setAuthSession({
    token: "test-token",
    apiBaseUrl: "http://localhost:8000",
    organizationId: "org-1",
    userEmail: "owner@example.com",
  });
});

describe("SettingsPage Google account section", () => {
  it("hides the Google section entirely when no Google account is linked", async () => {
    mockEndpoints(meResponse({ has_google_account: false }));
    renderWithProviders(<SettingsPage />);

    await waitFor(() => expect(screen.getByText("owner@example.com")).toBeInTheDocument());
    expect(screen.queryByText("Google account")).not.toBeInTheDocument();
  });

  it("shows Connected and a Disconnect button when linked with a password also set", async () => {
    mockEndpoints(meResponse({ has_google_account: true, password_set: true }));
    renderWithProviders(<SettingsPage />);

    expect(await screen.findByText("Google account")).toBeInTheDocument();
    expect(screen.getByText("Connected")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Disconnect Google" })).toBeInTheDocument();
  });

  it("shows a set-a-password notice instead of a button for a Google-only account", async () => {
    mockEndpoints(meResponse({ has_google_account: true, password_set: false }));
    renderWithProviders(<SettingsPage />);

    expect(await screen.findByText("Google account")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Disconnect Google" })).not.toBeInTheDocument();
    expect(screen.getByText(/currently your only way to sign in/)).toBeInTheDocument();
  });

  it("disconnects successfully and refreshes the section", async () => {
    let disconnected = false;
    mockEndpoints(
      meResponse({ has_google_account: true, password_set: true }),
      () => {
        disconnected = true;
        return Promise.resolve({ message: "ok" });
      }
    );
    // After disconnect, the follow-up /auth/me refresh should reflect no more Google link.
    apiFetchMock.mockImplementation((path: string, init?: RequestInit) => {
      if (path === "/auth/me") {
        return Promise.resolve(meResponse({ has_google_account: !disconnected, password_set: true }));
      }
      if (path.endsWith("/auth/google/disconnect") && init?.method === "POST") {
        disconnected = true;
        return Promise.resolve({ message: "ok" });
      }
      if (path.startsWith("/organizations/")) return Promise.resolve(PROFILE);
      return Promise.reject(new Error(`unexpected call: ${path}`));
    });

    renderWithProviders(<SettingsPage />);

    const button = await screen.findByRole("button", { name: "Disconnect Google" });
    button.click();

    await waitFor(() => expect(screen.queryByText("Google account")).not.toBeInTheDocument());
  });

  it("shows an error message when disconnect fails", async () => {
    const { ApiError } = await import("@/lib/api");
    mockEndpoints(meResponse({ has_google_account: true, password_set: true }), () =>
      Promise.reject(
        new ApiError("Request failed (409)", 409, {
          detail: { code: "no_other_auth_method", message: "Set a password first." },
        })
      )
    );

    renderWithProviders(<SettingsPage />);

    const button = await screen.findByRole("button", { name: "Disconnect Google" });
    button.click();

    expect(await screen.findByText("Set a password first.")).toBeInTheDocument();
  });
});
