import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { PlanLimitReachedDetail } from "@/lib/types";
import { renderWithProviders, screen } from "@/tests/test-utils";

import { PlanLimitReachedDialog } from "./PlanLimitReachedDialog";

const detail: PlanLimitReachedDetail = {
  code: "plan_limit_reached",
  resource: "customers",
  used: 100,
  limit: 100,
  plan: { id: "plan_free", code: "free", name: "Free" },
  message: "You've reached your plan's customers limit (100/100) on the Free plan.",
};

describe("PlanLimitReachedDialog", () => {
  it("renders nothing when detail is null", () => {
    renderWithProviders(<PlanLimitReachedDialog detail={null} onClose={vi.fn()} />);
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("renders resource, used/limit, and current plan from the structured detail -- never the raw message", async () => {
    renderWithProviders(<PlanLimitReachedDialog detail={detail} onClose={vi.fn()} />);

    expect(await screen.findByRole("alertdialog")).toBeInTheDocument();
    expect(screen.getByText("Customers")).toBeInTheDocument();
    expect(screen.getByText("100 / 100")).toBeInTheDocument();
    expect(screen.getByText("Free")).toBeInTheDocument();
    expect(screen.queryByText(detail.message)).not.toBeInTheDocument();
  });

  it("never shows pricing, payment, or upgrade UI", async () => {
    renderWithProviders(<PlanLimitReachedDialog detail={detail} onClose={vi.fn()} />);
    await screen.findByRole("alertdialog");

    expect(screen.queryByText(/upgrade/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/\$/)).not.toBeInTheDocument();
    expect(screen.queryByText(/payment/i)).not.toBeInTheDocument();
    expect(screen.getAllByRole("button")).toHaveLength(1);
  });

  it("calls onClose when the close button is clicked", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(<PlanLimitReachedDialog detail={detail} onClose={onClose} />);

    await user.click(await screen.findByRole("button", { name: "Got it" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("calls onClose on Escape", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(<PlanLimitReachedDialog detail={detail} onClose={onClose} />);

    await screen.findByRole("alertdialog");
    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
