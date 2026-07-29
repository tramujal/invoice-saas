import { describe, expect, it } from "vitest";

import { renderWithProviders, screen } from "@/tests/test-utils";

import CheckoutCancelPage from "./page";

describe("CheckoutCancelPage", () => {
  it("renders a cancellation message and a link back to Plan & Limits", () => {
    renderWithProviders(<CheckoutCancelPage />);

    expect(screen.getByText("Checkout canceled")).toBeInTheDocument();
    expect(
      screen.getByText(
        "You canceled checkout -- your current plan is unchanged. You can try again anytime."
      )
    ).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "Back to Plan & Limits" });
    expect(link).toHaveAttribute("href", "/settings/plan");
  });
});
