import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders, screen, waitFor } from "@/tests/test-utils";

import LoginPage from "./page";

const replaceMock = vi.fn();
let mockSearchParams = new URLSearchParams();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock, push: vi.fn() }),
  useSearchParams: () => mockSearchParams,
}));

const publicGetMock = vi.fn();
const authRequestMock = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    publicGet: (...args: unknown[]) => publicGetMock(...args),
    authRequest: (...args: unknown[]) => authRequestMock(...args),
  };
});

/** publicGet is called for both GET /public/config and GET
 * /auth/google/config -- routes each by its `path` argument so a single
 * mock implementation can answer both distinctly. */
function mockPublicGet(options: { registrationsEnabled?: boolean; googleEnabled?: boolean } = {}) {
  const { registrationsEnabled = true, googleEnabled = false } = options;
  publicGetMock.mockImplementation((_apiBaseUrl: string, path: string) => {
    if (path === "/auth/google/config") return Promise.resolve({ enabled: googleEnabled });
    return Promise.resolve({ maintenance_mode: false, registrations_enabled: registrationsEnabled });
  });
}

beforeEach(() => {
  window.localStorage.clear();
  replaceMock.mockReset();
  publicGetMock.mockReset();
  authRequestMock.mockReset();
  mockSearchParams = new URLSearchParams();
});

describe("LoginPage registration gating", () => {
  it("shows the Create account tab when the public config reports registrations enabled", async () => {
    mockPublicGet({ registrationsEnabled: true });
    renderWithProviders(<LoginPage />);

    await waitFor(() => expect(publicGetMock).toHaveBeenCalled());
    expect(screen.getByRole("button", { name: "Create account" })).toBeInTheDocument();
  });

  it("disables the Create account tab and shows a notice when registrations are disabled", async () => {
    mockPublicGet({ registrationsEnabled: false });
    renderWithProviders(<LoginPage />);

    await waitFor(() =>
      expect(
        screen.getByText("New registrations are currently disabled by the platform administrator.")
      ).toBeInTheDocument()
    );
    expect(screen.queryByRole("button", { name: "Create account" })).not.toBeInTheDocument();
  });

  it("stays on the sign-in form even if a direct ?mode=register link is used while registrations are disabled", async () => {
    mockPublicGet({ registrationsEnabled: false });
    renderWithProviders(<LoginPage />);

    await waitFor(() => expect(screen.getByText(/currently disabled/)).toBeInTheDocument());
    expect(screen.queryByLabelText("Organization name")).not.toBeInTheDocument();
  });

  it("fails open (keeps registration visible) if the public config request errors", async () => {
    publicGetMock.mockRejectedValue(new Error("network down"));
    renderWithProviders(<LoginPage />);

    await waitFor(() => expect(publicGetMock).toHaveBeenCalled());
    expect(screen.getByRole("button", { name: "Create account" })).toBeInTheDocument();
  });
});

describe("LoginPage Google Sign-In", () => {
  const originalLocation = window.location;

  beforeEach(() => {
    // window.location.href is a real navigation in the browser -- stubbed
    // here so clicking the button doesn't crash jsdom, and so the test can
    // assert exactly what URL the button tried to navigate to.
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...originalLocation, href: "" },
    });
  });

  afterEach(() => {
    Object.defineProperty(window, "location", { configurable: true, value: originalLocation });
  });

  it("shows Continue with Google when the backend reports it's enabled", async () => {
    mockPublicGet({ googleEnabled: true });
    renderWithProviders(<LoginPage />);

    expect(await screen.findByRole("button", { name: /Continue with Google/ })).toBeInTheDocument();
  });

  it("hides the Google button when the backend reports it's disabled", async () => {
    mockPublicGet({ googleEnabled: false });
    renderWithProviders(<LoginPage />);

    await waitFor(() => expect(publicGetMock).toHaveBeenCalled());
    expect(screen.queryByRole("button", { name: /Continue with Google/ })).not.toBeInTheDocument();
  });

  it("navigates the whole page to /auth/google/start when clicked", async () => {
    mockPublicGet({ googleEnabled: true });
    renderWithProviders(<LoginPage />);

    const button = await screen.findByRole("button", { name: /Continue with Google/ });
    button.click();

    expect(window.location.href).toContain("/auth/google/start");
  });

  it("exchanges a google_handoff code on landing and signs the user in", async () => {
    mockSearchParams = new URLSearchParams("google_handoff=handoff-code-123");
    mockPublicGet({ googleEnabled: true });
    authRequestMock.mockResolvedValue({
      access_token: "tok",
      user: { id: "u1", email: "googleuser@example.com", email_verified: true, platform_role: null },
      organizations: [
        { id: "org1", name: "Acme", currency_code: "USD", language: "en", permissions: [], status: "active" },
      ],
    });

    renderWithProviders(<LoginPage />);

    await waitFor(() =>
      expect(authRequestMock).toHaveBeenCalledWith(
        expect.any(String),
        "/auth/google/exchange",
        { code: "handoff-code-123" }
      )
    );
    await waitFor(() => expect(replaceMock).toHaveBeenCalledWith("/dashboard"));
  });

  it("shows a translated error message for a google_error redirect", async () => {
    mockSearchParams = new URLSearchParams("google_error=google_denied");
    mockPublicGet({ googleEnabled: true });

    renderWithProviders(<LoginPage />);

    expect(await screen.findByText("Google sign-in was cancelled.")).toBeInTheDocument();
  });
});
