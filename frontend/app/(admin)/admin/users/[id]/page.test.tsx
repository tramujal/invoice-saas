import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setAuthSession } from "@/lib/auth-storage";
import type { PlatformUserDetail } from "@/lib/types";
import { renderWithProviders, screen, waitFor, within } from "@/tests/test-utils";

import PlatformUserDetailPage from "./page";

vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/users/user-1",
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  useParams: () => ({ id: "user-1" }),
}));

const apiFetchMock = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    apiFetch: (...args: unknown[]) => apiFetchMock(...args),
  };
});

const activeUser: PlatformUserDetail = {
  id: "user-1",
  email: "target@example.com",
  email_verified: false,
  status: "active",
  platform_role: null,
  created_at: "2026-01-01T00:00:00Z",
  organizations: [],
};

beforeEach(() => {
  apiFetchMock.mockReset();
  window.localStorage.clear();
  setAuthSession({
    token: "test-token",
    apiBaseUrl: "http://localhost:8000",
    userEmail: "admin@example.com",
  });
});

describe("PlatformUserDetailPage actions", () => {
  it("shows Disable, Force verify, and Grant Super Admin for an active unverified user with no platform role", async () => {
    apiFetchMock.mockResolvedValue(activeUser);
    renderWithProviders(<PlatformUserDetailPage />);

    await waitFor(() => expect(screen.getByRole("button", { name: "Disable" })).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Force verify" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Grant Super Admin" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Enable" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Revoke Super Admin" })).not.toBeInTheDocument();
  });

  it("shows Enable and Revoke Super Admin for a disabled user with a platform role", async () => {
    apiFetchMock.mockResolvedValue({
      ...activeUser,
      status: "disabled",
      email_verified: true,
      platform_role: "super_admin",
    });
    renderWithProviders(<PlatformUserDetailPage />);

    await waitFor(() => expect(screen.getByRole("button", { name: "Enable" })).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Revoke Super Admin" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Disable" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Force verify" })).not.toBeInTheDocument();
  });

  it("hides disable/enable and role actions entirely when viewing your own account", async () => {
    apiFetchMock.mockResolvedValue({ ...activeUser, email: "admin@example.com" });
    renderWithProviders(<PlatformUserDetailPage />);

    await waitFor(() => expect(screen.getByText("admin@example.com")).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "Disable" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Enable" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Grant Super Admin" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Revoke Super Admin" })).not.toBeInTheDocument();
  });

  it("disable requires typing the exact email and a reason, then updates from the mutation response only", async () => {
    apiFetchMock.mockResolvedValueOnce(activeUser);
    const user = userEvent.setup();
    renderWithProviders(<PlatformUserDetailPage />);

    await waitFor(() => expect(screen.getByRole("button", { name: "Disable" })).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Disable" }));

    const dialog = screen.getByRole("dialog");
    const confirmButton = within(dialog).getByRole("button", { name: "Disable user" });
    expect(confirmButton).toBeDisabled();

    await user.type(within(dialog).getByLabelText("Type target@example.com to confirm"), "wrong");
    await user.type(within(dialog).getByLabelText("Reason"), "policy violation");
    expect(confirmButton).toBeDisabled();

    await user.clear(within(dialog).getByLabelText("Type target@example.com to confirm"));
    await user.type(within(dialog).getByLabelText("Type target@example.com to confirm"), "target@example.com");
    expect(confirmButton).not.toBeDisabled();

    apiFetchMock.mockResolvedValueOnce({ ...activeUser, status: "disabled" });
    await user.click(confirmButton);

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.getByText("Disabled")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Enable" })).toBeInTheDocument();

    // Exactly one call for the initial load, one for the mutation.
    expect(apiFetchMock).toHaveBeenCalledTimes(2);
    expect(apiFetchMock.mock.calls[1][0]).toBe("/admin/users/user-1/disable");
  });

  it("shows a controlled error and keeps the dialog open on a conflicted mutation, without optimistic status change", async () => {
    const { ApiError } = await import("@/lib/api");
    apiFetchMock.mockResolvedValueOnce(activeUser);
    const user = userEvent.setup();
    renderWithProviders(<PlatformUserDetailPage />);

    await waitFor(() => expect(screen.getByRole("button", { name: "Disable" })).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Disable" }));

    const dialog = screen.getByRole("dialog");
    await user.type(within(dialog).getByLabelText("Type target@example.com to confirm"), "target@example.com");
    await user.type(within(dialog).getByLabelText("Reason"), "policy violation");

    apiFetchMock.mockRejectedValueOnce(
      new ApiError("conflict", 409, { detail: { code: "user_already_disabled" } })
    );
    await user.click(within(dialog).getByRole("button", { name: "Disable user" }));

    await waitFor(() =>
      expect(within(dialog).getByRole("alert")).toHaveTextContent("This user is already disabled.")
    );
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
  });

  it("force-verify requires only a confirm click, no typed input", async () => {
    apiFetchMock.mockResolvedValueOnce(activeUser);
    const user = userEvent.setup();
    renderWithProviders(<PlatformUserDetailPage />);

    await waitFor(() => expect(screen.getByRole("button", { name: "Force verify" })).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Force verify" }));

    const dialog = screen.getByRole("dialog");
    expect(within(dialog).queryByRole("textbox")).not.toBeInTheDocument();

    apiFetchMock.mockResolvedValueOnce({ ...activeUser, email_verified: true });
    await user.click(within(dialog).getByRole("button", { name: "Verify email" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(apiFetchMock.mock.calls[1][0]).toBe("/admin/users/user-1/verify-email");
  });

  it("send-password-reset never renders a token or reset link anywhere on the page", async () => {
    apiFetchMock.mockResolvedValueOnce(activeUser);
    const user = userEvent.setup();
    renderWithProviders(<PlatformUserDetailPage />);

    await waitFor(() => expect(screen.getByRole("button", { name: "Send reset email" })).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Send reset email" }));

    const dialog = screen.getByRole("dialog");
    apiFetchMock.mockResolvedValueOnce({ message: "A password reset email has been sent to target@example.com." });
    await user.click(within(dialog).getByRole("button", { name: "Send email" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(apiFetchMock.mock.calls[1][0]).toBe("/admin/users/user-1/send-password-reset");
    expect(document.body.textContent).not.toMatch(/token=/);
  });
});
