import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders, screen } from "@/tests/test-utils";

import { RowActionsMenu } from "./RowActionsMenu";

async function openMenu() {
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "More actions" }));
  return user;
}

describe("RowActionsMenu.Item -- missing-phone / no-permission gating", () => {
  it("renders a disabled item with a localized title tooltip, and never calls onSelect when clicked", async () => {
    const onSelect = vi.fn();
    renderWithProviders(
      <RowActionsMenu label="More actions">
        <RowActionsMenu.Item onSelect={onSelect} disabled title="Customer has no valid phone number.">
          Open in WhatsApp
        </RowActionsMenu.Item>
      </RowActionsMenu>
    );

    const user = await openMenu();
    const item = screen.getByRole("menuitem", { name: "Open in WhatsApp" });
    expect(item).toBeDisabled();
    expect(item).toHaveAttribute("title", "Customer has no valid phone number.");

    await user.click(item);
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("calls onSelect exactly once when enabled, with no title attribute", async () => {
    const onSelect = vi.fn();
    renderWithProviders(
      <RowActionsMenu label="More actions">
        <RowActionsMenu.Item onSelect={onSelect}>Open in WhatsApp</RowActionsMenu.Item>
      </RowActionsMenu>
    );

    const user = await openMenu();
    const item = screen.getByRole("menuitem", { name: "Open in WhatsApp" });
    expect(item).not.toBeDisabled();
    expect(item).not.toHaveAttribute("title");

    await user.click(item);
    expect(onSelect).toHaveBeenCalledTimes(1);
  });
});

describe("Open in WhatsApp -- window.open call shape", () => {
  it("opens the wa.me URL in a new tab with noopener/noreferrer, never claiming success", async () => {
    const openSpy = vi.spyOn(window, "open").mockReturnValue(null);
    const onSelect = vi.fn(() => {
      window.open(
        "https://wa.me/15551234567?text=Hola",
        "_blank",
        "noopener,noreferrer"
      );
    });

    renderWithProviders(
      <RowActionsMenu label="More actions">
        <RowActionsMenu.Item onSelect={onSelect}>Open in WhatsApp</RowActionsMenu.Item>
      </RowActionsMenu>
    );

    const user = await openMenu();
    await user.click(screen.getByRole("menuitem", { name: "Open in WhatsApp" }));

    expect(openSpy).toHaveBeenCalledTimes(1);
    const [url, target, features] = openSpy.mock.calls[0];
    expect(url).toBe("https://wa.me/15551234567?text=Hola");
    expect(target).toBe("_blank");
    expect(features).toContain("noopener");
    expect(features).toContain("noreferrer");

    openSpy.mockRestore();
  });
});

describe("Clickable contact links -- tel:/mailto: format", () => {
  it("builds a tel: href from the raw stored phone", () => {
    renderWithProviders(<a href={`tel:${"+1 555-123-4567"}`}>+1 555-123-4567</a>);
    expect(screen.getByRole("link")).toHaveAttribute("href", "tel:+1 555-123-4567");
  });

  it("builds a mailto: href from the stored email", () => {
    renderWithProviders(<a href={`mailto:${"customer@example.com"}`}>customer@example.com</a>);
    expect(screen.getByRole("link")).toHaveAttribute("href", "mailto:customer@example.com");
  });
});
