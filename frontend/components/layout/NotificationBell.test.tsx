import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setAuthSession } from "@/lib/auth-storage";
import type { Notification, PaginatedNotificationsResponse } from "@/lib/types";
import { renderWithProviders, screen, waitFor } from "@/tests/test-utils";

import { NotificationBell } from "./NotificationBell";

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

describe("NotificationBell", () => {
  it("shows the unread count badge from the initial fetch", async () => {
    const response: PaginatedNotificationsResponse = {
      total: 2,
      unread_count: 2,
      items: [makeNotification(), makeNotification({ id: "notif-2" })],
    };
    apiFetchMock.mockResolvedValue(response);

    renderWithProviders(<NotificationBell />);

    expect(await screen.findByText("2")).toBeInTheDocument();
  });

  it("shows no badge when there are no unread notifications", async () => {
    apiFetchMock.mockResolvedValue({ total: 0, unread_count: 0, items: [] });
    renderWithProviders(<NotificationBell />);

    await waitFor(() => expect(apiFetchMock).toHaveBeenCalled());
    expect(screen.queryByText("0")).not.toBeInTheDocument();
  });

  it("opens the dropdown and shows the preview items", async () => {
    const response: PaginatedNotificationsResponse = {
      total: 1,
      unread_count: 1,
      items: [makeNotification()],
    };
    apiFetchMock.mockResolvedValue(response);

    const user = userEvent.setup();
    renderWithProviders(<NotificationBell />);
    await waitFor(() => expect(apiFetchMock).toHaveBeenCalled());

    await user.click(screen.getByRole("button", { name: "Notifications" }));

    expect(await screen.findByText("Invoice created")).toBeInTheDocument();
    expect(screen.getByText("Invoice INV-1 was created.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View all notifications" })).toHaveAttribute(
      "href",
      "/settings/notifications"
    );
  });

  it("shows an empty message when there are no notifications at all", async () => {
    apiFetchMock.mockResolvedValue({ total: 0, unread_count: 0, items: [] });
    const user = userEvent.setup();
    renderWithProviders(<NotificationBell />);
    await waitFor(() => expect(apiFetchMock).toHaveBeenCalled());

    await user.click(screen.getByRole("button", { name: "Notifications" }));

    expect(await screen.findByText("You're all caught up.")).toBeInTheDocument();
  });

  it("marks a notification read on click and decrements the badge", async () => {
    const initial: PaginatedNotificationsResponse = {
      total: 1,
      unread_count: 1,
      items: [makeNotification()],
    };
    apiFetchMock.mockImplementation((path: string) => {
      if (path.endsWith("/read")) {
        return Promise.resolve(makeNotification({ read_at: "2026-01-02T00:00:00Z" }));
      }
      return Promise.resolve(initial);
    });

    const user = userEvent.setup();
    renderWithProviders(<NotificationBell />);
    await screen.findByText("1");

    await user.click(screen.getByRole("button", { name: "Notifications" }));
    await user.click(await screen.findByText("Invoice created"));

    await waitFor(() => expect(screen.queryByText("1")).not.toBeInTheDocument());
  });
});
