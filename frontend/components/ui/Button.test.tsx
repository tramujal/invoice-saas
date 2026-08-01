import { describe, expect, it } from "vitest";

import { renderWithProviders, screen } from "@/tests/test-utils";

import { Button } from "./Button";

describe("Button", () => {
  it("renders children normally when not loading", () => {
    renderWithProviders(<Button>Save</Button>);
    const button = screen.getByRole("button", { name: "Save" });
    expect(button).not.toBeDisabled();
    expect(button).not.toHaveAttribute("aria-busy");
  });

  it("disables itself and marks aria-busy when loading", () => {
    renderWithProviders(<Button loading>Saving…</Button>);
    const button = screen.getByRole("button", { name: "Saving…" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-busy", "true");
  });

  it("stays disabled when explicitly disabled, independent of loading", () => {
    renderWithProviders(<Button disabled>Save</Button>);
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });
});
