import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { setAuthSession } from "@/lib/auth-storage";
import { renderWithProviders, screen, waitFor } from "@/tests/test-utils";

import { InviteMemberForm } from "./InviteMemberForm";

const apiFetchMock = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    apiFetch: (...args: unknown[]) => apiFetchMock(...args),
  };
});

beforeEach(() => {
  apiFetchMock.mockReset();
  setAuthSession({
    token: "test-token",
    apiBaseUrl: "http://localhost:8000",
    organizationId: "org-1",
    userEmail: "self@example.com",
  });
});

async function submit(email: string) {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText(/email/i), email);
  await user.click(screen.getByRole("button", { name: "Send invitation" }));
}

describe("InviteMemberForm plan-limit handling", () => {
  it("shows the PlanLimitReachedDialog (not a toast) when the invite endpoint returns plan_limit_reached", async () => {
    apiFetchMock.mockRejectedValue(
      new ApiError("Request failed (409)", 409, {
        detail: {
          code: "plan_limit_reached",
          resource: "users",
          used: 2,
          limit: 2,
          plan: { id: "plan_free", code: "free", name: "Free" },
          message: "You've reached your plan's users limit (2/2) on the Free plan.",
        },
      })
    );
    renderWithProviders(<InviteMemberForm onInvited={vi.fn()} />);

    await submit("newperson@example.com");

    expect(await screen.findByRole("alertdialog")).toBeInTheDocument();
    expect(screen.getByText("Users")).toBeInTheDocument();
    expect(screen.getByText("2 / 2")).toBeInTheDocument();
    expect(screen.queryByText(/upgrade/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/payment/i)).not.toBeInTheDocument();
  });

  it("falls back to a toast (no dialog) for a non-plan-limit error", async () => {
    apiFetchMock.mockRejectedValue(new ApiError("Server exploded", 500));
    renderWithProviders(<InviteMemberForm onInvited={vi.fn()} />);

    await submit("newperson@example.com");

    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });
});
