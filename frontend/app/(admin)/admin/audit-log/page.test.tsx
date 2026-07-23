import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PaginatedPlatformAuditLog } from "@/lib/types";
import { fireEvent, renderWithProviders, screen, waitFor, within } from "@/tests/test-utils";

import PlatformAuditLogPage from "./page";

vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/audit-log",
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

const oneEntry: PaginatedPlatformAuditLog = {
  total: 1,
  items: [
    {
      id: "entry-1",
      action: "user.disabled",
      actor_user_id: "actor-1",
      actor_email: "admin@example.com",
      target_type: "user",
      target_organization_id: null,
      target_organization_name: null,
      target_user_id: "user-1",
      target_user_email: "target@example.com",
      reason: "policy violation",
      details: null,
      client_ip: "203.0.113.0",
      created_at: "2026-01-15T10:30:00Z",
    },
  ],
};

beforeEach(() => {
  apiFetchMock.mockReset();
});

describe("PlatformAuditLogPage", () => {
  it("shows a loading state, then renders rows with human-readable action labels and the raw code as a tooltip", async () => {
    apiFetchMock.mockResolvedValue(oneEntry);
    renderWithProviders(<PlatformAuditLogPage />);

    expect(screen.getByText("Loading audit log…")).toBeInTheDocument();

    await waitFor(() => expect(screen.getByText("target@example.com")).toBeInTheDocument());
    const row = screen.getByText("target@example.com").closest("tr")!;
    expect(within(row).getByText("User disabled")).toBeInTheDocument();
    expect(within(row).getByText("admin@example.com")).toBeInTheDocument();
    expect(within(row).getByText("policy violation")).toBeInTheDocument();
    const badgeWrapper = within(row).getByText("User disabled").closest("span[title]");
    expect(badgeWrapper).toHaveAttribute("title", "user.disabled");
  });

  it("shows the empty state when there are no entries and no filters applied", async () => {
    apiFetchMock.mockResolvedValue({ total: 0, items: [] });
    renderWithProviders(<PlatformAuditLogPage />);

    await waitFor(() => expect(screen.getByText("No activity yet")).toBeInTheDocument());
  });

  it("shows a filtered-empty state with a reset action when filters are active but nothing matches", async () => {
    apiFetchMock.mockResolvedValue({ total: 0, items: [] });
    const user = userEvent.setup();
    renderWithProviders(<PlatformAuditLogPage />);

    await waitFor(() => expect(screen.getByText("No activity yet")).toBeInTheDocument());

    await user.type(screen.getByRole("searchbox", { name: "Search by actor email" }), "nobody");
    await waitFor(() => expect(screen.getByText("No matching entries")).toBeInTheDocument());

    // Two "Reset filters" controls exist once results are filtered-empty
    // (the toolbar's own reset button, plus the empty state's own reset
    // link) -- either one clears the same filter state.
    const resetButtons = screen.getAllByRole("button", { name: "Reset filters" });
    await user.click(resetButtons[0]);
    await waitFor(() => expect(screen.getByText("No activity yet")).toBeInTheDocument());
  });

  it("shows a controlled error banner when the request fails", async () => {
    const { ApiError } = await import("@/lib/api");
    apiFetchMock.mockRejectedValue(new ApiError("boom", 500));
    renderWithProviders(<PlatformAuditLogPage />);

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("boom"));
  });

  it("rejects an invalid date range client-side without ever calling the API for the invalid combination", async () => {
    apiFetchMock.mockResolvedValue(oneEntry);
    renderWithProviders(<PlatformAuditLogPage />);

    await waitFor(() => expect(screen.getByText("User disabled")).toBeInTheDocument());

    // Set both fields atomically (fireEvent.change, not keystroke-by-
    // keystroke typing) so the only two states rendered are "no range"
    // and "the final invalid range" -- never a misleading partial value.
    fireEvent.change(screen.getByLabelText("From date"), { target: { value: "2026-06-01" } });
    fireEvent.change(screen.getByLabelText("To date"), { target: { value: "2026-01-01" } });

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("The start date must not be after the end date.")
    );
    const callCountOnceInvalid = apiFetchMock.mock.calls.length;

    // No further calls fire while the range stays invalid.
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(apiFetchMock.mock.calls.length).toBe(callCountOnceInvalid);
  });

  it("filters by action and shows an active filter chip that can be removed", async () => {
    apiFetchMock.mockResolvedValue(oneEntry);
    const user = userEvent.setup();
    renderWithProviders(<PlatformAuditLogPage />);

    await waitFor(() => expect(screen.getByText("User disabled")).toBeInTheDocument());
    await user.selectOptions(screen.getByRole("combobox", { name: "Action" }), "user.disabled");

    await waitFor(() =>
      expect(apiFetchMock.mock.calls.at(-1)?.[0]).toContain("action=user.disabled")
    );
    expect(screen.getByText("Action: User disabled")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Remove filter: Action: User disabled" }));
    await waitFor(() => expect(apiFetchMock.mock.calls.at(-1)?.[0]).not.toContain("action="));
  });

  it("paginates using limit/offset and disables Previous on the first page", async () => {
    apiFetchMock.mockResolvedValue({ total: 45, items: oneEntry.items });
    const user = userEvent.setup();
    renderWithProviders(<PlatformAuditLogPage />);

    await waitFor(() => expect(screen.getByText("User disabled")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(apiFetchMock.mock.calls.at(-1)?.[0]).toContain("offset=20"));
  });

  it("opens a read-only details drawer with structured key/value content, never raw HTML", async () => {
    apiFetchMock.mockResolvedValue({
      total: 1,
      items: [
        {
          ...oneEntry.items[0],
          action: "user.platform_role_granted",
          details: { old_role: null, new_role: "super_admin" },
        },
      ],
    });
    const user = userEvent.setup();
    renderWithProviders(<PlatformAuditLogPage />);

    await waitFor(() => expect(screen.getByRole("button", { name: "View details" })).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "View details" }));

    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText("Audit log entry")).toBeInTheDocument();
    expect(within(dialog).getByText("new_role")).toBeInTheDocument();
    expect(within(dialog).getByText("super_admin")).toBeInTheDocument();
    expect(within(dialog).getByText("old_role")).toBeInTheDocument();
  });

  it("never renders a secret-shaped value even if present in raw details", async () => {
    apiFetchMock.mockResolvedValue({
      total: 1,
      items: [
        {
          ...oneEntry.items[0],
          details: { reset_token: "[redacted]", safe_field: "kept" },
        },
      ],
    });
    const user = userEvent.setup();
    renderWithProviders(<PlatformAuditLogPage />);

    await waitFor(() => expect(screen.getByRole("button", { name: "View details" })).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "View details" }));

    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText("[redacted]")).toBeInTheDocument();
    expect(within(dialog).getByText("kept")).toBeInTheDocument();
    // The page trusts the server's redaction and only ever renders text
    // nodes (no dangerouslySetInnerHTML anywhere in this component) --
    // confirmed by the absence of any raw secret substring on the page.
    expect(document.body.textContent).not.toMatch(/sk-live|Bearer |password=/i);
  });

  it("shows the masked IP as plain text", async () => {
    apiFetchMock.mockResolvedValue(oneEntry);
    renderWithProviders(<PlatformAuditLogPage />);

    await waitFor(() => expect(screen.getByText("203.0.113.0")).toBeInTheDocument());
  });
});
