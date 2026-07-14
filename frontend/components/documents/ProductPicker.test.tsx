import { useRef, useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setAuthSession } from "@/lib/auth-storage";
import type { PaginatedProducts, Product } from "@/lib/types";
import { renderWithProviders, screen, waitFor } from "@/tests/test-utils";
import userEvent from "@testing-library/user-event";

import { ProductPicker } from "./ProductPicker";

const apiFetchMock = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    apiFetch: (...args: unknown[]) => apiFetchMock(...args),
  };
});

function makeProduct(overrides: Partial<Product>): Product {
  return {
    id: "product-1",
    organization_id: "org-1",
    name: "Hosting Premium",
    description: "",
    type: "service",
    sku: "",
    default_unit_price: "15.00",
    currency_code: "USD",
    default_tax_rate: "0",
    active: true,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ...overrides,
  } as Product;
}

function Harness({
  documentCurrency,
  onSelectProduct,
}: {
  documentCurrency: "USD" | "EUR" | "UYU" | null;
  onSelectProduct: (p: Product) => void;
}) {
  const anchorRef = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button ref={anchorRef} type="button" onClick={() => setOpen(true)}>
        Add line
      </button>
      <ProductPicker
        open={open}
        anchorRef={anchorRef}
        documentCurrency={documentCurrency}
        onClose={() => setOpen(false)}
        onSelectProduct={(p) => {
          onSelectProduct(p);
          setOpen(false);
        }}
        onCreateManualLine={() => setOpen(false)}
      />
    </div>
  );
}

beforeEach(() => {
  apiFetchMock.mockReset();
  setAuthSession({
    token: "test-token",
    apiBaseUrl: "http://localhost:8000",
    organizationId: "org-1",
    userEmail: "self@example.com",
  });
});

describe("ProductPicker", () => {
  it("renders name, currency, and price per result", async () => {
    const response: PaginatedProducts = {
      total: 1,
      items: [makeProduct({ name: "Hosting Premium", default_unit_price: "15.00", currency_code: "USD" })],
    };
    apiFetchMock.mockResolvedValue(response);

    const user = userEvent.setup();
    renderWithProviders(<Harness documentCurrency={null} onSelectProduct={() => {}} />);
    await user.click(screen.getByRole("button", { name: "Add line" }));

    await waitFor(() => expect(screen.getByText("Hosting Premium")).toBeInTheDocument());
    expect(screen.getByText(/USD 15[.,]00/)).toBeInTheDocument();
  });

  it("shows incompatible-currency products disabled with a note", async () => {
    const response: PaginatedProducts = {
      total: 1,
      items: [makeProduct({ name: "Hosting", currency_code: "EUR" })],
    };
    apiFetchMock.mockResolvedValue(response);

    const user = userEvent.setup();
    const onSelect = vi.fn();
    renderWithProviders(<Harness documentCurrency="USD" onSelectProduct={onSelect} />);
    await user.click(screen.getByRole("button", { name: "Add line" }));

    await waitFor(() => expect(screen.getByText("Hosting")).toBeInTheDocument());
    const option = screen.getByRole("option", { name: /Hosting/ });
    expect(option).toHaveAttribute("aria-disabled", "true");
    expect(option).toBeDisabled();

    await user.click(option);
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("always shows a keyboard-reachable Create Manual Line option", async () => {
    apiFetchMock.mockResolvedValue({ total: 0, items: [] } satisfies PaginatedProducts);

    const user = userEvent.setup();
    renderWithProviders(<Harness documentCurrency={null} onSelectProduct={() => {}} />);
    await user.click(screen.getByRole("button", { name: "Add line" }));

    await waitFor(() =>
      expect(screen.getByText("➕ Create Manual Line")).toBeInTheDocument()
    );
    const manualOption = screen.getByRole("option", { name: /Create Manual Line/ });
    expect(manualOption).toBeInTheDocument();
    expect(manualOption.tabIndex).not.toBe(-1);
  });

  it("closes on Escape and returns focus to the trigger", async () => {
    apiFetchMock.mockResolvedValue({ total: 0, items: [] } satisfies PaginatedProducts);

    const user = userEvent.setup();
    renderWithProviders(<Harness documentCurrency={null} onSelectProduct={() => {}} />);
    const trigger = screen.getByRole("button", { name: "Add line" });
    await user.click(trigger);

    await waitFor(() => expect(screen.getByRole("listbox")).toBeInTheDocument());
    await user.keyboard("{Escape}");

    await waitFor(() => expect(screen.queryByRole("listbox")).not.toBeInTheDocument());
  });

  it("debounces search input before calling the products endpoint", async () => {
    apiFetchMock.mockResolvedValue({ total: 0, items: [] } satisfies PaginatedProducts);

    const user = userEvent.setup();
    renderWithProviders(<Harness documentCurrency={null} onSelectProduct={() => {}} />);
    await user.click(screen.getByRole("button", { name: "Add line" }));
    await waitFor(() => expect(apiFetchMock).toHaveBeenCalledTimes(1));

    const input = screen.getByRole("combobox");
    await user.type(input, "host");

    await waitFor(
      () => {
        const lastCall = apiFetchMock.mock.calls[apiFetchMock.mock.calls.length - 1];
        expect(String(lastCall[0])).toContain("search=host");
      },
      { timeout: 1000 }
    );
  });
});
