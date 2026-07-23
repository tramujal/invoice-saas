import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PaginatedPlatformOrganizations } from "@/lib/types";
import { renderWithProviders, screen, waitFor } from "@/tests/test-utils";

import PlatformOrganizationsPage from "./page";

vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/organizations",
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

const oneOrg: PaginatedPlatformOrganizations = {
  total: 1,
  items: [
    {
      id: "org-1",
      name: "Rivera Design Studio",
      business_name: null,
      status: "active",
      owner_email: "owner@example.com",
      members_count: 2,
      invoices_count: 5,
      quotes_count: 3,
      customers_count: 4,
      created_at: "2026-01-01T00:00:00Z",
      last_activity_at: "2026-06-01T00:00:00Z",
    },
  ],
};

beforeEach(() => {
  apiFetchMock.mockReset();
});

describe("PlatformOrganizationsPage", () => {
  it("shows a loading state before data arrives", () => {
    apiFetchMock.mockReturnValue(new Promise(() => {}));
    renderWithProviders(<PlatformOrganizationsPage />);

    expect(screen.getByText("Loading organizations…")).toBeInTheDocument();
  });

  it("renders an empty state when there are no organizations", async () => {
    apiFetchMock.mockResolvedValue({ total: 0, items: [] });
    renderWithProviders(<PlatformOrganizationsPage />);

    await waitFor(() => expect(screen.getByText("No organizations yet")).toBeInTheDocument());
  });

  it("shows an error message when the request fails", async () => {
    const { ApiError } = await import("@/lib/api");
    apiFetchMock.mockRejectedValue(new ApiError("Server exploded", 500));
    renderWithProviders(<PlatformOrganizationsPage />);

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Server exploded"));
  });

  it("renders organization rows once loaded", async () => {
    apiFetchMock.mockResolvedValue(oneOrg);
    renderWithProviders(<PlatformOrganizationsPage />);

    await waitFor(() => expect(screen.getByText("Rivera Design Studio")).toBeInTheDocument());
    expect(screen.getByText("owner@example.com")).toBeInTheDocument();
  });

  it("debounces search input into a `search` query param", async () => {
    apiFetchMock.mockResolvedValue({ total: 0, items: [] });
    const user = userEvent.setup();
    renderWithProviders(<PlatformOrganizationsPage />);
    await waitFor(() => expect(apiFetchMock).toHaveBeenCalledTimes(1));

    await user.type(screen.getByPlaceholderText("Search by organization name…"), "rivera");

    await waitFor(() => {
      const lastCall = apiFetchMock.mock.calls.at(-1)?.[0] as string;
      expect(lastCall).toContain("search=rivera");
    });
  });

  it("paginates via Previous/Next buttons", async () => {
    apiFetchMock.mockResolvedValue({
      total: 45,
      items: Array.from({ length: 20 }, (_, i) => ({ ...oneOrg.items[0], id: `org-${i}`, name: `Org ${i}` })),
    });
    const user = userEvent.setup();
    renderWithProviders(<PlatformOrganizationsPage />);
    await waitFor(() => expect(screen.getByText(/Page 1 of/)).toBeInTheDocument());

    const nextButton = screen.getByRole("button", { name: "Next" });
    expect(nextButton).not.toBeDisabled();
    await user.click(nextButton);

    await waitFor(() => {
      const lastCall = apiFetchMock.mock.calls.at(-1)?.[0] as string;
      expect(lastCall).toContain("offset=20");
    });
  });
});
