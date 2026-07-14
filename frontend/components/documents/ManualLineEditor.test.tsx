import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders, screen } from "@/tests/test-utils";

import { ManualLineEditor } from "./ManualLineEditor";

describe("ManualLineEditor", () => {
  it("shows a currency select when the document has no currency yet", () => {
    renderWithProviders(
      <ManualLineEditor
        open
        documentCurrency={null}
        defaultCurrency="USD"
        onClose={() => {}}
        onSubmit={() => {}}
      />
    );
    expect(screen.getByRole("combobox")).toBeInTheDocument();
  });

  it("shows a fixed currency badge (no select) once the document currency is set", () => {
    renderWithProviders(
      <ManualLineEditor
        open
        documentCurrency="EUR"
        defaultCurrency="USD"
        onClose={() => {}}
        onSubmit={() => {}}
      />
    );
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(screen.getByText(/EUR/)).toBeInTheDocument();
  });

  it("validates required description before submitting", async () => {
    const onSubmit = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(
      <ManualLineEditor
        open
        documentCurrency="USD"
        defaultCurrency="USD"
        onClose={() => {}}
        onSubmit={onSubmit}
      />
    );

    await user.click(screen.getByRole("button", { name: /add line/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/description/i);
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("submits the entered manual line data", async () => {
    const onSubmit = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(
      <ManualLineEditor
        open
        documentCurrency="USD"
        defaultCurrency="USD"
        onClose={() => {}}
        onSubmit={onSubmit}
      />
    );

    const [descriptionInput] = screen.getAllByRole("textbox");
    await user.type(descriptionInput, "Consulting");
    await user.click(screen.getByRole("button", { name: /add line/i }));

    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ currencyCode: "USD", description: "Consulting" })
    );
  });
});
