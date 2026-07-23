import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PaginatedPlatformUsers } from "@/lib/types";
import { renderWithProviders, screen, waitFor } from "@/tests/test-utils";

import PlatformUsersPage from "./page";

vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/users",
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

const oneUser: PaginatedPlatformUsers = {
  total: 1,
  items: [
    {
      id: "user-1",
      email: "isabella.rivera@example.com",
      email_verified: true,
      status: "active",
      platform_role: null,
      organizations_count: 1,
      created_at: "2026-01-01T00:00:00Z",
    },
  ],
};

beforeEach(() => {
  apiFetchMock.mockReset();
});

describe("PlatformUsersPage", () => {
  it("shows a loading state before data arrives", () => {
    apiFetchMock.mockReturnValue(new Promise(() => {}));
    renderWithProviders(<PlatformUsersPage />);

    expect(screen.getByText("Loading users…")).toBeInTheDocument();
  });

  it("renders an empty state when there are no users", async () => {
    apiFetchMock.mockResolvedValue({ total: 0, items: [] });
    renderWithProviders(<PlatformUsersPage />);

    await waitFor(() => expect(screen.getByText("No users yet")).toBeInTheDocument());
  });

  it("shows an error message when the request fails", async () => {
    const { ApiError } = await import("@/lib/api");
    apiFetchMock.mockRejectedValue(new ApiError("Server exploded", 500));
    renderWithProviders(<PlatformUsersPage />);

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Server exploded"));
  });

  it("renders user rows once loaded, never showing a password field", async () => {
    apiFetchMock.mockResolvedValue(oneUser);
    renderWithProviders(<PlatformUsersPage />);

    await waitFor(() => expect(screen.getByText("isabella.rivera@example.com")).toBeInTheDocument());
    expect(document.body.textContent?.toLowerCase()).not.toContain("password");
  });

  it("applies the has_platform_role filter as a query param", async () => {
    apiFetchMock.mockResolvedValue({ total: 0, items: [] });
    const user = userEvent.setup();
    renderWithProviders(<PlatformUsersPage />);
    await waitFor(() => expect(apiFetchMock).toHaveBeenCalledTimes(1));

    await user.selectOptions(screen.getByLabelText("Platform admin"), "yes");

    await waitFor(() => {
      const lastCall = apiFetchMock.mock.calls.at(-1)?.[0] as string;
      expect(lastCall).toContain("has_platform_role=true");
    });
  });

  it("paginates via Previous/Next buttons", async () => {
    apiFetchMock.mockResolvedValue({
      total: 45,
      items: Array.from({ length: 20 }, (_, i) => ({ ...oneUser.items[0], id: `user-${i}`, email: `u${i}@example.com` })),
    });
    const user = userEvent.setup();
    renderWithProviders(<PlatformUsersPage />);
    await waitFor(() => expect(screen.getByText(/Page 1 of/)).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "Next" }));

    await waitFor(() => {
      const lastCall = apiFetchMock.mock.calls.at(-1)?.[0] as string;
      expect(lastCall).toContain("offset=20");
    });
  });
});
