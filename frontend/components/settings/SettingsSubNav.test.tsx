import { describe, expect, it, vi } from "vitest";

import { renderWithProviders, screen } from "@/tests/test-utils";

import { SettingsSubNav } from "./SettingsSubNav";

vi.mock("next/navigation", () => ({
  usePathname: () => "/settings/webhooks",
}));

/** Phase UX1 regression coverage: the nav must contain its own horizontal
 * overflow rather than letting it bubble up to the page. jsdom doesn't
 * compute real layout, so this asserts the STRUCTURE that produces that
 * behavior in a real browser (a scrollable wrapper containing a
 * shrink-to-content nav of non-wrapping tabs) rather than measured pixel
 * widths -- see the browser-level 320px/390px verification for the
 * actual rendered-width assertion. */
describe("SettingsSubNav", () => {
  it("wraps the tab row in its own horizontally-scrollable container", () => {
    renderWithProviders(<SettingsSubNav />);

    const nav = screen.getByRole("navigation", { name: "Settings navigation" });
    const scrollContainer = nav.parentElement;
    expect(scrollContainer).not.toBeNull();
    expect(scrollContainer).toHaveClass("overflow-x-auto");
    // w-max lets the nav grow past its container's width instead of
    // being forced to shrink its (unbreakable-text) tabs below their
    // natural size -- the scroll container above is what keeps that
    // overflow from reaching the page.
    expect(nav).toHaveClass("w-max");
  });

  it("renders every tab as a non-wrapping, non-shrinking flex item", () => {
    renderWithProviders(<SettingsSubNav />);

    const links = screen.getAllByRole("link");
    expect(links.length).toBeGreaterThanOrEqual(7);
    for (const link of links) {
      expect(link).toHaveClass("shrink-0");
      expect(link).toHaveClass("whitespace-nowrap");
    }
  });

  it("marks the active tab with aria-current and distinct styling", () => {
    renderWithProviders(<SettingsSubNav />);

    const activeLink = screen.getByRole("link", { name: "Webhooks" });
    expect(activeLink).toHaveAttribute("aria-current", "page");
    expect(activeLink).toHaveClass("border-slate-900");
    expect(activeLink).toHaveClass("text-slate-900");

    const inactiveLink = screen.getByRole("link", { name: "Organization" });
    expect(inactiveLink).not.toHaveAttribute("aria-current");
    expect(inactiveLink).toHaveClass("border-transparent");
  });

  it("gives the nav an accessible label for screen readers", () => {
    renderWithProviders(<SettingsSubNav />);
    expect(screen.getByRole("navigation", { name: "Settings navigation" })).toBeInTheDocument();
  });
});
