import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders, screen, waitFor } from "@/tests/test-utils";

import LoginPage from "./page";

const replaceMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock, push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
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

beforeEach(() => {
  window.localStorage.clear();
  replaceMock.mockReset();
  publicGetMock.mockReset();
  authRequestMock.mockReset();
});

describe("LoginPage registration gating", () => {
  it("shows the Create account tab when the public config reports registrations enabled", async () => {
    publicGetMock.mockResolvedValue({ maintenance_mode: false, registrations_enabled: true });
    renderWithProviders(<LoginPage />);

    await waitFor(() => expect(publicGetMock).toHaveBeenCalled());
    expect(screen.getByRole("button", { name: "Create account" })).toBeInTheDocument();
  });

  it("disables the Create account tab and shows a notice when registrations are disabled", async () => {
    publicGetMock.mockResolvedValue({ maintenance_mode: false, registrations_enabled: false });
    renderWithProviders(<LoginPage />);

    await waitFor(() =>
      expect(
        screen.getByText("New registrations are currently disabled by the platform administrator.")
      ).toBeInTheDocument()
    );
    expect(screen.queryByRole("button", { name: "Create account" })).not.toBeInTheDocument();
  });

  it("stays on the sign-in form even if a direct ?mode=register link is used while registrations are disabled", async () => {
    publicGetMock.mockResolvedValue({ maintenance_mode: false, registrations_enabled: false });
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
