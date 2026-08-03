import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { CustomerDuplicateCheckResponse } from "@/lib/types";
import { renderWithProviders, screen } from "@/tests/test-utils";

import { CustomerDuplicateDialog } from "./CustomerDuplicateDialog";

const warningResult: CustomerDuplicateCheckResponse = {
  severity: "warning",
  matches: [
    {
      customer_id: "cust-1",
      customer_name: "Juan Pérez",
      email: "juan@example.com",
      phone: "",
      tax_id: "",
      reasons: ["email"],
    },
  ],
};

const blockingResult: CustomerDuplicateCheckResponse = {
  severity: "blocking",
  matches: [
    {
      customer_id: "cust-2",
      customer_name: "Acme Inc",
      email: "",
      phone: "",
      tax_id: "123456789",
      reasons: ["tax_id"],
    },
  ],
};

function noop() {}

describe("CustomerDuplicateDialog", () => {
  it("renders nothing when result is null", () => {
    renderWithProviders(
      <CustomerDuplicateDialog
        result={null}
        onCancel={noop}
        onCreateAnyway={noop}
        onOpenExisting={noop}
      />
    );
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("renders nothing for 'none' or 'suggestion' severity -- those never open a dialog", () => {
    renderWithProviders(
      <CustomerDuplicateDialog
        result={{ severity: "suggestion", matches: [] }}
        onCancel={noop}
        onCreateAnyway={noop}
        onOpenExisting={noop}
      />
    );
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("warning: shows Open existing customer, Create anyway, and Cancel, with Cancel focused by default", async () => {
    renderWithProviders(
      <CustomerDuplicateDialog
        result={warningResult}
        onCancel={noop}
        onCreateAnyway={noop}
        onOpenExisting={noop}
      />
    );

    expect(await screen.findByRole("alertdialog")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open existing customer" })).toBeInTheDocument();
    const createAnyway = screen.getByRole("button", { name: "Create anyway" });
    expect(createAnyway).toBeInTheDocument();
    const cancel = screen.getByRole("button", { name: "Cancel" });
    expect(cancel).toHaveFocus();
  });

  it("blocking: shows only Open existing customer and Cancel -- never Create anyway", async () => {
    renderWithProviders(
      <CustomerDuplicateDialog
        result={blockingResult}
        onCancel={noop}
        onCreateAnyway={noop}
        onOpenExisting={noop}
      />
    );

    expect(await screen.findByRole("alertdialog")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open existing customer" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create anyway" })).not.toBeInTheDocument();
    expect(screen.getByText(/already belongs to another customer/i)).toBeInTheDocument();
  });

  it("calls onOpenExisting with the matched customer's id", async () => {
    const onOpenExisting = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(
      <CustomerDuplicateDialog
        result={warningResult}
        onCancel={noop}
        onCreateAnyway={noop}
        onOpenExisting={onOpenExisting}
      />
    );

    await user.click(await screen.findByRole("button", { name: "Open existing customer" }));
    expect(onOpenExisting).toHaveBeenCalledWith("cust-1");
  });

  it("calls onCreateAnyway only from the warning variant's explicit button", async () => {
    const onCreateAnyway = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(
      <CustomerDuplicateDialog
        result={warningResult}
        onCancel={noop}
        onCreateAnyway={onCreateAnyway}
        onOpenExisting={noop}
      />
    );

    await user.click(await screen.findByRole("button", { name: "Create anyway" }));
    expect(onCreateAnyway).toHaveBeenCalledTimes(1);
  });

  it("Escape calls onCancel, never onCreateAnyway", async () => {
    const onCancel = vi.fn();
    const onCreateAnyway = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(
      <CustomerDuplicateDialog
        result={warningResult}
        onCancel={onCancel}
        onCreateAnyway={onCreateAnyway}
        onOpenExisting={noop}
      />
    );

    await screen.findByRole("alertdialog");
    await user.keyboard("{Escape}");
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onCreateAnyway).not.toHaveBeenCalled();
  });

  it("uses a custom createAnywayLabel when provided (edit flow: 'Save anyway')", async () => {
    renderWithProviders(
      <CustomerDuplicateDialog
        result={warningResult}
        onCancel={noop}
        onCreateAnyway={noop}
        onOpenExisting={noop}
        createAnywayLabel="Save anyway"
      />
    );

    expect(await screen.findByRole("button", { name: "Save anyway" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create anyway" })).not.toBeInTheDocument();
  });
});
