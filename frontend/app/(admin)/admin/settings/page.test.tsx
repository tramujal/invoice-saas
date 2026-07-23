import userEvent from "@testing-library/user-event";
import { within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PlatformSettings } from "@/lib/types";
import { renderWithProviders, screen, waitFor } from "@/tests/test-utils";

import PlatformSettingsPage from "./page";

vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/settings",
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

const baseSettings: PlatformSettings = {
  maintenance_mode: false,
  registrations_enabled: true,
  ai_enabled: true,
  emails_enabled: true,
  invoice_reminders_enabled: true,
  quote_reminders_enabled: true,
  default_language: "en",
  default_currency: "USD",
  updated_at: "2026-01-01T00:00:00Z",
  updated_by_email: null,
  version: 1,
  ai_provider: "gemini",
  email_provider: "resend",
  cors_allowed_origins: ["https://app.example.com"],
};

beforeEach(() => {
  apiFetchMock.mockReset();
});

describe("PlatformSettingsPage", () => {
  it("shows an error message when the request fails", async () => {
    const { ApiError } = await import("@/lib/api");
    apiFetchMock.mockRejectedValue(new ApiError("Server exploded", 500));
    renderWithProviders(<PlatformSettingsPage />);

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Server exploded"));
  });

  it("renders infrastructure status read-only, with no inputs to edit it", async () => {
    apiFetchMock.mockResolvedValue(baseSettings);
    renderWithProviders(<PlatformSettingsPage />);

    await waitFor(() => expect(screen.getByText("gemini")).toBeInTheDocument());
    expect(screen.getByText("resend")).toBeInTheDocument();
    expect(screen.getByText("https://app.example.com")).toBeInTheDocument();
  });

  it("caps a long CORS origins list with a '+N more' summary instead of dumping every entry", async () => {
    apiFetchMock.mockResolvedValue({
      ...baseSettings,
      ai_provider: null,
      email_provider: null,
      cors_allowed_origins: [
        "https://a.example.com",
        "https://b.example.com",
        "https://c.example.com",
        "https://d.example.com",
        "https://e.example.com",
      ],
    } satisfies PlatformSettings);
    renderWithProviders(<PlatformSettingsPage />);

    await waitFor(() => expect(screen.getByText("+2 more")).toBeInTheDocument());
    expect(screen.queryByText("https://d.example.com")).not.toBeInTheDocument();
  });

  it("renders every editable toggle from the loaded settings, with no unsaved-changes bar yet", async () => {
    apiFetchMock.mockResolvedValue(baseSettings);
    renderWithProviders(<PlatformSettingsPage />);

    await waitFor(() => expect(screen.getByRole("switch", { name: "Maintenance mode" })).toBeInTheDocument());
    expect(screen.getByRole("switch", { name: "Maintenance mode" })).toHaveAttribute("aria-checked", "false");
    expect(screen.getByRole("switch", { name: "New registrations" })).toHaveAttribute("aria-checked", "true");
    expect(screen.queryByText(/unsaved change/)).not.toBeInTheDocument();
  });

  it("toggling a switch reveals the unsaved-changes bar, and discarding resets it", async () => {
    apiFetchMock.mockResolvedValue(baseSettings);
    const user = userEvent.setup();
    renderWithProviders(<PlatformSettingsPage />);

    await waitFor(() => expect(screen.getByRole("switch", { name: "AI assistant" })).toBeInTheDocument());
    await user.click(screen.getByRole("switch", { name: "AI assistant" }));

    expect(screen.getByText("1 unsaved change(s)")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Discard" }));
    expect(screen.queryByText(/unsaved change/)).not.toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "AI assistant" })).toHaveAttribute("aria-checked", "true");
  });

  it("shows a diff summary and a specific warning when enabling maintenance mode, then saves and applies the response", async () => {
    apiFetchMock.mockResolvedValueOnce(baseSettings);
    const user = userEvent.setup();
    renderWithProviders(<PlatformSettingsPage />);

    await waitFor(() => expect(screen.getByRole("switch", { name: "Maintenance mode" })).toBeInTheDocument());
    await user.click(screen.getByRole("switch", { name: "Maintenance mode" }));
    await user.click(screen.getByRole("button", { name: "Review & save" }));

    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText("Maintenance mode blocks tenant usage across the entire platform.")).toBeInTheDocument();
    const confirmButton = within(dialog).getByRole("button", { name: "Apply changes" });
    expect(confirmButton).toBeDisabled();

    await user.type(within(dialog).getByLabelText("Reason"), "scheduled maintenance window");
    expect(confirmButton).not.toBeDisabled();

    apiFetchMock.mockResolvedValueOnce({ ...baseSettings, maintenance_mode: true, updated_by_email: "admin@example.com" });
    await user.click(confirmButton);

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.getByText("Maintenance mode is currently ON. Tenant usage is blocked platform-wide.")).toBeInTheDocument();
    expect(screen.queryByText(/unsaved change/)).not.toBeInTheDocument();

    expect(apiFetchMock).toHaveBeenCalledTimes(2);
    expect(apiFetchMock.mock.calls[1][0]).toBe("/admin/settings");
    expect(apiFetchMock.mock.calls[1][1]).toMatchObject({ method: "PATCH" });
    expect(JSON.parse(apiFetchMock.mock.calls[1][1].body)).toEqual({
      reason: "scheduled maintenance window",
      expected_version: 1,
      maintenance_mode: true,
    });
  });

  it("shows a controlled error and keeps the dialog open when the save fails", async () => {
    const { ApiError } = await import("@/lib/api");
    apiFetchMock.mockResolvedValueOnce(baseSettings);
    const user = userEvent.setup();
    renderWithProviders(<PlatformSettingsPage />);

    await waitFor(() => expect(screen.getByRole("switch", { name: "AI assistant" })).toBeInTheDocument());
    await user.click(screen.getByRole("switch", { name: "AI assistant" }));
    await user.click(screen.getByRole("button", { name: "Review & save" }));

    const dialog = screen.getByRole("dialog");
    await user.type(within(dialog).getByLabelText("Reason"), "temporary outage");

    apiFetchMock.mockRejectedValueOnce(new ApiError("Something went wrong. Please try again.", 500));
    await user.click(within(dialog).getByRole("button", { name: "Apply changes" }));

    await waitFor(() =>
      expect(within(dialog).getByText("Something went wrong. Please try again.")).toBeInTheDocument()
    );
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    // Never optimistic -- the switch must still show its pending (not yet
    // persisted) value, and the unsaved-changes bar must still be present.
    expect(screen.getByText("1 unsaved change(s)")).toBeInTheDocument();
  });

  it("does not show a warning for routine changes like the default language", async () => {
    apiFetchMock.mockResolvedValueOnce(baseSettings);
    const user = userEvent.setup();
    renderWithProviders(<PlatformSettingsPage />);

    await waitFor(() => expect(screen.getByLabelText("Default language")).toBeInTheDocument());
    await user.selectOptions(screen.getByLabelText("Default language"), "es");
    await user.click(screen.getByRole("button", { name: "Review & save" }));

    const dialog = screen.getByRole("dialog");
    expect(within(dialog).queryByRole("alert")).not.toBeInTheDocument();
  });

  describe("optimistic concurrency", () => {
    async function triggerConflict(user: ReturnType<typeof userEvent.setup>) {
      const { ApiError } = await import("@/lib/api");
      apiFetchMock.mockResolvedValueOnce(baseSettings);
      renderWithProviders(<PlatformSettingsPage />);

      await waitFor(() => expect(screen.getByRole("switch", { name: "AI assistant" })).toBeInTheDocument());
      await user.click(screen.getByRole("switch", { name: "AI assistant" }));
      await user.click(screen.getByRole("button", { name: "Review & save" }));

      const dialog = screen.getByRole("dialog");
      await user.type(within(dialog).getByLabelText("Reason"), "disable AI");

      apiFetchMock.mockRejectedValueOnce(
        new ApiError("conflict", 409, {
          detail: {
            code: "platform_settings_version_conflict",
            message: "These settings were changed by another administrator. Reload and try again.",
            current_version: 2,
          },
        })
      );
      await user.click(within(dialog).getByRole("button", { name: "Apply changes" }));
      await waitFor(() =>
        expect(screen.getByText("Someone else just saved a change")).toBeInTheDocument()
      );
    }

    it("PATCH sends the version originally loaded from GET", async () => {
      const user = userEvent.setup();
      await triggerConflict(user);

      expect(JSON.parse(apiFetchMock.mock.calls[1][1].body)).toMatchObject({ expected_version: 1 });
    });

    it("shows the dedicated conflict warning and closes the save dialog", async () => {
      const user = userEvent.setup();
      await triggerConflict(user);

      expect(screen.getByRole("alertdialog")).toBeInTheDocument();
      expect(
        screen.getByText(/These settings were changed by another administrator after you opened this page/)
      ).toBeInTheDocument();
      // The save dialog closed -- only the conflict dialog remains.
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });

    it("does not clear the unsaved form values when a conflict occurs", async () => {
      const user = userEvent.setup();
      await triggerConflict(user);

      // The AI toggle the user changed is still showing its pending
      // (unsaved) value, and the unsaved-changes bar is still present.
      expect(screen.getByRole("switch", { name: "AI assistant" })).toHaveAttribute("aria-checked", "false");
      expect(screen.getByText("1 unsaved change(s)")).toBeInTheDocument();
    });

    it("never automatically retries the PATCH after a conflict", async () => {
      const user = userEvent.setup();
      await triggerConflict(user);

      // Exactly one GET (initial load) + one PATCH (the rejected one) --
      // nothing retried it automatically.
      expect(apiFetchMock).toHaveBeenCalledTimes(2);
    });

    it("cancelling the conflict dialog keeps the user's local unsaved values", async () => {
      const user = userEvent.setup();
      await triggerConflict(user);

      await user.click(screen.getByRole("button", { name: "Keep reviewing my changes" }));

      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
      expect(screen.getByRole("switch", { name: "AI assistant" })).toHaveAttribute("aria-checked", "false");
      expect(screen.getByText("1 unsaved change(s)")).toBeInTheDocument();
      // Still exactly the two prior calls -- cancelling made no request.
      expect(apiFetchMock).toHaveBeenCalledTimes(2);
    });

    it("reloading latest settings requires the explicit button and replaces values and version", async () => {
      const user = userEvent.setup();
      await triggerConflict(user);

      apiFetchMock.mockResolvedValueOnce({
        ...baseSettings,
        ai_enabled: false,
        maintenance_mode: true,
        version: 2,
        updated_by_email: "other-admin@example.com",
      });
      await user.click(screen.getByRole("button", { name: "Reload latest settings" }));

      await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
      // The reload replaced the draft with the fresh server state -- the
      // user's own unsaved AI-disable change is gone, replaced by
      // whatever the other admin actually saved.
      expect(screen.getByRole("switch", { name: "AI assistant" })).toHaveAttribute("aria-checked", "false");
      expect(screen.getByText("Settings version: 2")).toBeInTheDocument();
      expect(screen.queryByText(/unsaved change/)).not.toBeInTheDocument();
    });

    it("disables the save button while a PATCH is pending", async () => {
      apiFetchMock.mockResolvedValueOnce(baseSettings);
      const user = userEvent.setup();
      renderWithProviders(<PlatformSettingsPage />);

      await waitFor(() => expect(screen.getByRole("switch", { name: "AI assistant" })).toBeInTheDocument());
      await user.click(screen.getByRole("switch", { name: "AI assistant" }));
      await user.click(screen.getByRole("button", { name: "Review & save" }));

      const dialog = screen.getByRole("dialog");
      await user.type(within(dialog).getByLabelText("Reason"), "test");

      let resolvePatch: (value: unknown) => void = () => {};
      apiFetchMock.mockReturnValueOnce(new Promise((resolve) => (resolvePatch = resolve)));
      const confirmButton = within(dialog).getByRole("button", { name: "Apply changes" });
      await user.click(confirmButton);

      expect(confirmButton).toBeDisabled();
      resolvePatch({ ...baseSettings, ai_enabled: false, version: 2 });
    });
  });
});
