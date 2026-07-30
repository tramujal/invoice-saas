import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setAuthSession } from "@/lib/auth-storage";
import type { PaginatedAuditEntries, PaginatedMembers } from "@/lib/types";
import { fireEvent, renderWithProviders, screen, waitFor, within } from "@/tests/test-utils";

import SettingsAuditLogPage from "./page";

vi.mock("next/navigation", () => ({
  usePathname: () => "/settings/audit-log",
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

const members: PaginatedMembers = {
  total: 1,
  items: [
    {
      id: "member-1",
      organization_id: "org-1",
      user_id: "actor-1",
      user_email: "owner@example.com",
      role: "owner",
      status: "active",
      invited_by_email: null,
      invited_at: null,
      accepted_at: "2026-01-01T00:00:00Z",
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
      permissions: [],
    },
  ],
};

const oneEntry: PaginatedAuditEntries = {
  total: 1,
  items: [
    {
      id: "entry-1",
      organization_id: "org-1",
      actor_user_id: "actor-1",
      actor_email: "owner@example.com",
      event_type: "customer.created",
      resource_type: "customer",
      resource_id: "cust-1",
      metadata: { id: "cust-1", name: "Acme" },
      created_at: "2026-01-15T10:30:00Z",
    },
  ],
};

function mockDefault(entries: PaginatedAuditEntries) {
  apiFetchMock.mockImplementation((path: string) => {
    if (path.includes("/members")) return Promise.resolve(members);
    if (path.includes("/audit-entries")) return Promise.resolve(entries);
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
    userEmail: "self@example.com",
  });
});

describe("SettingsAuditLogPage", () => {
  it("shows a loading state, then renders rows with a human-readable event label and resource", async () => {
    mockDefault(oneEntry);
    renderWithProviders(<SettingsAuditLogPage />);

    expect(screen.getByText("Loading audit entries…")).toBeInTheDocument();

    // "owner@example.com"/"Customer created" also appear as <option>
    // text in the Actor/Event filter selects -- scope to the table body
    // to find the actual data row unambiguously.
    await waitFor(() => expect(document.querySelector("tbody")).toHaveTextContent("owner@example.com"));
    const tbody = document.querySelector("tbody")!;
    const row = within(tbody).getByText("owner@example.com").closest("tr")!;
    expect(within(row).getByText("Customer created")).toBeInTheDocument();
    expect(within(row).getByText(/customer.*cust-1/)).toBeInTheDocument();
  });

  it("shows a system-actor label when actor_email is null", async () => {
    mockDefault({
      total: 1,
      items: [{ ...oneEntry.items[0], actor_user_id: null, actor_email: null }],
    });
    renderWithProviders(<SettingsAuditLogPage />);

    await waitFor(() => expect(screen.getByText("System (no user)")).toBeInTheDocument());
  });

  it("shows the empty state when there are no entries and no filters applied", async () => {
    mockDefault({ total: 0, items: [] });
    renderWithProviders(<SettingsAuditLogPage />);

    await waitFor(() => expect(screen.getByText("No audit entries yet")).toBeInTheDocument());
  });

  it("shows a filtered-empty state with a reset action when filters are active but nothing matches", async () => {
    mockDefault({ total: 0, items: [] });
    const user = userEvent.setup();
    renderWithProviders(<SettingsAuditLogPage />);

    await waitFor(() => expect(screen.getByText("No audit entries yet")).toBeInTheDocument());

    await user.type(screen.getByRole("searchbox", { name: "Search by resource ID" }), "nope");
    await waitFor(() => expect(screen.getByText("No matching audit entries")).toBeInTheDocument());

    const resetButtons = screen.getAllByRole("button", { name: "Reset filters" });
    await user.click(resetButtons[0]);
    await waitFor(() => expect(screen.getByText("No audit entries yet")).toBeInTheDocument());
  });

  it("shows a controlled error banner when the request fails", async () => {
    const { ApiError } = await import("@/lib/api");
    apiFetchMock.mockImplementation((path: string) => {
      if (path.includes("/members")) return Promise.resolve(members);
      return Promise.reject(new ApiError("boom", 500));
    });
    renderWithProviders(<SettingsAuditLogPage />);

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("boom"));
  });

  it("rejects an invalid date range client-side and stops fetching while it stays invalid", async () => {
    mockDefault(oneEntry);
    renderWithProviders(<SettingsAuditLogPage />);

    await waitFor(() => expect(screen.getByText("Customer created")).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText("From"), { target: { value: "2026-06-01" } });
    fireEvent.change(screen.getByLabelText("To"), { target: { value: "2026-01-01" } });

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("The start date must not be after the end date.")
    );
    const callCountOnceInvalid = apiFetchMock.mock.calls.length;

    // No further calls fire while the range stays invalid.
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(apiFetchMock.mock.calls.length).toBe(callCountOnceInvalid);
  });

  it("filters by event type and shows a removable active-filter chip", async () => {
    mockDefault(oneEntry);
    const user = userEvent.setup();
    renderWithProviders(<SettingsAuditLogPage />);

    await waitFor(() => expect(screen.getByText("Customer created")).toBeInTheDocument());
    await user.selectOptions(screen.getByRole("combobox", { name: "Event" }), "customer.created");

    await waitFor(() =>
      expect(apiFetchMock.mock.calls.at(-1)?.[0]).toContain("event_type=customer.created")
    );
    expect(screen.getByText("Event: Customer created")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Remove filter: Event: Customer created" }));
    await waitFor(() => expect(apiFetchMock.mock.calls.at(-1)?.[0]).not.toContain("event_type="));
  });

  it("paginates using limit/offset and disables Previous on the first page", async () => {
    mockDefault({ total: 45, items: oneEntry.items });
    const user = userEvent.setup();
    renderWithProviders(<SettingsAuditLogPage />);

    await waitFor(() => expect(screen.getByText("Customer created")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(apiFetchMock.mock.calls.at(-1)?.[0]).toContain("offset=20"));
  });

  it("opens a read-only details drawer with the event's metadata", async () => {
    mockDefault(oneEntry);
    const user = userEvent.setup();
    renderWithProviders(<SettingsAuditLogPage />);

    await waitFor(() => expect(screen.getByRole("button", { name: "View details" })).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "View details" }));

    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText("Audit entry details")).toBeInTheDocument();
    expect(within(dialog).getByText("name")).toBeInTheDocument();
    expect(within(dialog).getByText("Acme")).toBeInTheDocument();
  });

  it("shows 'no additional data' when metadata is null", async () => {
    mockDefault({ total: 1, items: [{ ...oneEntry.items[0], metadata: null }] });
    const user = userEvent.setup();
    renderWithProviders(<SettingsAuditLogPage />);

    await waitFor(() => expect(screen.getByRole("button", { name: "View details" })).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "View details" }));

    expect(within(screen.getByRole("dialog")).getByText("No additional data recorded.")).toBeInTheDocument();
  });
});
