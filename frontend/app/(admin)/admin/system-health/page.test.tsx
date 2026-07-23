import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PlatformSystemHealth } from "@/lib/types";
import { renderWithProviders, screen, waitFor } from "@/tests/test-utils";

import PlatformSystemHealthPage from "./page";

vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/system-health",
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}));

const apiFetchMock = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    apiFetch: (...args: unknown[]) => apiFetchMock(...args),
  };
});

const healthy: PlatformSystemHealth = {
  database_reachable: true,
  email_provider_configured: true,
  email_provider: "resend",
  ai_provider_configured: true,
  ai_provider: "gemini",
  reminder_emails_pending: 2,
  reminder_emails_sent_7d: 10,
  reminder_emails_failed_7d: 1,
};

beforeEach(() => {
  apiFetchMock.mockReset();
});

describe("PlatformSystemHealthPage", () => {
  it("shows an error message when the request fails", async () => {
    const { ApiError } = await import("@/lib/api");
    apiFetchMock.mockRejectedValue(new ApiError("Server exploded", 500));
    renderWithProviders(<PlatformSystemHealthPage />);

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Server exploded"));
  });

  it("renders only safe fields -- provider names, never secret values", async () => {
    apiFetchMock.mockResolvedValue(healthy);
    renderWithProviders(<PlatformSystemHealthPage />);

    await waitFor(() => expect(screen.getByText("Reachable")).toBeInTheDocument());
    expect(screen.getByText("Configured (resend)")).toBeInTheDocument();
    expect(screen.getByText("Configured (gemini)")).toBeInTheDocument();
    const bodyText = document.body.textContent ?? "";
    expect(bodyText.toLowerCase()).not.toMatch(/api[_-]?key|secret|token/);
  });

  it("shows unconfigured/unreachable states clearly", async () => {
    apiFetchMock.mockResolvedValue({
      database_reachable: false,
      email_provider_configured: false,
      email_provider: null,
      ai_provider_configured: false,
      ai_provider: null,
      reminder_emails_pending: 0,
      reminder_emails_sent_7d: 0,
      reminder_emails_failed_7d: 0,
    } satisfies PlatformSystemHealth);
    renderWithProviders(<PlatformSystemHealthPage />);

    await waitFor(() => expect(screen.getByText("Unreachable")).toBeInTheDocument());
    expect(screen.getAllByText("Not configured").length).toBeGreaterThan(0);
  });
});
