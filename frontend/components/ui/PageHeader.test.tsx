import { describe, expect, it } from "vitest";

import { renderWithProviders, screen } from "@/tests/test-utils";

import { PageHeader } from "./PageHeader";

/** Phase UX1 regression coverage: `title` is sometimes an unbroken string
 * with no natural wrap point (e.g. a user's email address, used as the
 * page title on the platform-admin user detail page) -- without min-w-0
 * on the wrapping flex item and break-words on the heading itself, a long
 * one forces this header (and the page) wider than the viewport on
 * mobile. */
describe("PageHeader", () => {
  it("lets a long, unbroken title wrap instead of overflowing", () => {
    const longTitle = "a-very-long-unbroken-user-email-address-with-no-spaces@example-corp.com";
    renderWithProviders(<PageHeader title={longTitle} />);

    const heading = screen.getByRole("heading", { name: longTitle });
    expect(heading).toHaveClass("break-words");
    expect(heading.parentElement).toHaveClass("min-w-0");
  });

  it("applies the same wrap protection to the subtitle", () => {
    const longSubtitle = "a-very-long-unbroken-business-name-with-no-spaces-1234567890-example";
    renderWithProviders(<PageHeader title="Title" subtitle={longSubtitle} />);

    expect(screen.getByText(longSubtitle)).toHaveClass("break-words");
  });

  it("still renders actions alongside the title", () => {
    renderWithProviders(<PageHeader title="Title" actions={<button type="button">Action</button>} />);
    expect(screen.getByRole("button", { name: "Action" })).toBeInTheDocument();
  });
});
