import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setAuthSession } from "@/lib/auth-storage";
import type { Notification, NotificationPreference, PaginatedNotificationsResponse } from "@/lib/types";
import { renderWithProviders, screen, waitFor } from "@/tests/test-utils";

import NotificationsSettingsPage from "./page";

vi.mock("next/navigation", () => ({
  usePathname: () => "/settings/notifications",
}));

const apiFetchMock = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    apiFetch: (...args: unknown[]) => apiFetchMock(...args),
  };
});

function makeNotification(overrides: Partial<Notification> = {}): Notification {
  return {
    id: "notif-1",
    event_type: "invoice.created",
    title: "Invoice created",
    body: "Invoice INV-1 was created.",
    object_type: "invoice",
    object_id: "inv-1",
    read_at: null,
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
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

function mockRoutes({
  list,
  preference,
}: {
  list: PaginatedNotificationsResponse;
  preference: NotificationPreference;
}) {
  apiFetchMock.mockImplementation((path: string, init?: RequestInit) => {
    if (path.includes("/notification-preferences")) {
      if (init?.method === "PATCH") {
        const body = JSON.parse(init.body as string) as NotificationPreference;
        return Promise.resolve(body);
      }
      return Promise.resolve(preference);
    }
    if (path.includes("/notifications/read-all")) {
      return Promise.resolve({ ...list, unread_count: 0, items: list.items.map((n) => ({ ...n, read_at: "2026-01-02T00:00:00Z" })) });
    }
    if (path.match(/\/notifications\/[^/]+\/read$/)) {
      return Promise.resolve(makeNotification({ read_at: "2026-01-02T00:00:00Z" }));
    }
    if (path.includes("/notifications")) {
      return Promise.resolve(list);
    }
    return Promise.reject(new Error(`unexpected call: ${path}`));
  });
}

describe("NotificationsSettingsPage", () => {
  it("renders the inbox and unread count", async () => {
    mockRoutes({
      list: { total: 1, unread_count: 1, items: [makeNotification()] },
      preference: { email_enabled: true },
    });

    renderWithProviders(<NotificationsSettingsPage />);

    expect(await screen.findByText("Invoice created")).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();
  });

  it("shows an empty state when there are no notifications", async () => {
    mockRoutes({
      list: { total: 0, unread_count: 0, items: [] },
      preference: { email_enabled: true },
    });

    renderWithProviders(<NotificationsSettingsPage />);

    expect(await screen.findByText("No notifications yet")).toBeInTheDocument();
  });

  it("marks a single notification read", async () => {
    mockRoutes({
      list: { total: 1, unread_count: 1, items: [makeNotification()] },
      preference: { email_enabled: true },
    });
    const user = userEvent.setup();
    renderWithProviders(<NotificationsSettingsPage />);
    await screen.findByText("Invoice created");

    await user.click(screen.getByRole("button", { name: "Mark read" }));

    await waitFor(() =>
      expect(apiFetchMock).toHaveBeenCalledWith(
        expect.stringMatching(/\/notifications\/notif-1\/read$/),
        expect.objectContaining({ method: "POST" })
      )
    );
  });

  it("marks all notifications read", async () => {
    mockRoutes({
      list: {
        total: 2,
        unread_count: 2,
        items: [
          makeNotification(),
          makeNotification({ id: "notif-2", title: "Quote sent", body: "Quote Q-1 was sent." }),
        ],
      },
      preference: { email_enabled: true },
    });
    const user = userEvent.setup();
    renderWithProviders(<NotificationsSettingsPage />);
    await screen.findByText("Invoice created");
    await screen.findByText("Quote sent");

    await user.click(screen.getByRole("button", { name: "Mark all read" }));

    await waitFor(() =>
      expect(apiFetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/notifications/read-all"),
        expect.objectContaining({ method: "POST" })
      )
    );
  });

  it("loads the email preference and toggles it", async () => {
    mockRoutes({
      list: { total: 0, unread_count: 0, items: [] },
      preference: { email_enabled: true },
    });
    const user = userEvent.setup();
    renderWithProviders(<NotificationsSettingsPage />);

    const checkbox = await screen.findByRole("checkbox", { name: "Email me about new activity" });
    await waitFor(() => expect(checkbox).toBeChecked());

    await user.click(checkbox);

    await waitFor(() =>
      expect(apiFetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/notification-preferences"),
        expect.objectContaining({ method: "PATCH" })
      )
    );
  });

  it("shows a load error message when the inbox fetch fails", async () => {
    apiFetchMock.mockImplementation((path: string) => {
      if (path.includes("/notification-preferences")) {
        return Promise.resolve({ email_enabled: true });
      }
      return Promise.reject(new Error("boom"));
    });

    renderWithProviders(<NotificationsSettingsPage />);

    expect(await screen.findByText("Failed to load your notifications.")).toBeInTheDocument();
  });
});
