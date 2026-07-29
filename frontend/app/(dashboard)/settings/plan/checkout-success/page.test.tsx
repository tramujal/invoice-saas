import { describe, expect, it } from "vitest";

import { renderWithProviders, screen } from "@/tests/test-utils";

import CheckoutSuccessPage from "./page";

describe("CheckoutSuccessPage", () => {
  it("renders a success message and a link back to Plan & Limits", () => {
    renderWithProviders(<CheckoutSuccessPage />);

    expect(screen.getByText("Payment received")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Your plan will update automatically within a few moments once we confirm the payment."
      )
    ).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "Back to Plan & Limits" });
    expect(link).toHaveAttribute("href", "/settings/plan");
  });
});
