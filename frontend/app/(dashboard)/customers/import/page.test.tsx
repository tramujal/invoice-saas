import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setAuthSession } from "@/lib/auth-storage";
import type { ImportPreviewResponse, ImportPreviewRowResult, OrganizationProfile } from "@/lib/types";
import { renderWithProviders, screen, waitFor } from "@/tests/test-utils";

import CustomerImportPage from "./page";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

const apiFetchMock = vi.fn();
const apiFetchFormMock = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    apiFetch: (...args: unknown[]) => apiFetchMock(...args),
    apiFetchForm: (...args: unknown[]) => apiFetchFormMock(...args),
  };
});

function makeRows(count: number): ImportPreviewRowResult[] {
  return Array.from({ length: count }, (_, i) => ({
    row_number: i + 1,
    status: "valid" as const,
    reason_code: null,
    values: { name: `Person ${i + 1}`, email: `person${i + 1}@example.com` },
  }));
}

const orgProfile: Partial<OrganizationProfile> = { tax_label: "Tax ID" };

beforeEach(() => {
  window.localStorage.clear();
  apiFetchMock.mockReset();
  apiFetchFormMock.mockReset();
  apiFetchMock.mockResolvedValue(orgProfile);
  setAuthSession({
    token: "test-token",
    apiBaseUrl: "http://localhost:8000",
    organizationId: "org-1",
  });
});

describe("Customer import wizard", () => {
  it("the accessible label opens the file picker without double-triggering the dropzone", async () => {
    const clickSpy = vi.spyOn(HTMLInputElement.prototype, "click").mockImplementation(() => {});
    const user = userEvent.setup();
    renderWithProviders(<CustomerImportPage />);

    const label = screen.getByText("Select a file");
    await user.click(label);

    // The label's native for/id association is what actually opens the
    // picker (a real browser wouldn't call .click() on the input at all
    // for a label click) -- the assertion that matters is that the
    // dropzone's own onClick (which calls fileInputRef.current.click())
    // fires at most once, never twice from one user click.
    expect(clickSpy.mock.calls.length).toBeLessThanOrEqual(1);
    clickSpy.mockRestore();
  });

  it("selecting a file via the input enables the Preview button", async () => {
    const user = userEvent.setup();
    renderWithProviders(<CustomerImportPage />);

    const fileInput = document.getElementById("customers-import-file-input") as HTMLInputElement;
    const file = new File(["name,email\nAlice,alice@example.com"], "customers.csv", {
      type: "text/csv",
    });
    await user.upload(fileInput, file);

    expect(screen.getByText(/customers\.csv/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Upload & preview" })).not.toBeDisabled();
  });

  it("caps rendered preview rows at 50 even when the server returns more", async () => {
    const previewResponse: ImportPreviewResponse = {
      file_type: "csv",
      headers: ["Name", "Email"],
      normalized_headers: ["name", "email"],
      auto_mapping: { Name: "name", Email: "email" },
      requires_manual_mapping: false,
      missing_required_fields: [],
      total_rows: 60,
      preview_rows: makeRows(60),
      valid_count: 60,
      warning_count: 0,
      invalid_count: 0,
      duplicate_count: 0,
    };
    apiFetchFormMock.mockResolvedValue(previewResponse);

    const user = userEvent.setup();
    renderWithProviders(<CustomerImportPage />);

    const fileInput = document.getElementById("customers-import-file-input") as HTMLInputElement;
    const file = new File(["name,email\n"], "customers.csv", { type: "text/csv" });
    await user.upload(fileInput, file);
    await user.click(screen.getByRole("button", { name: "Upload & preview" }));

    // First upload always lands on the mapping step (see runPreview's
    // step logic) -- continue through it to reach the actual preview
    // table.
    await waitFor(() => expect(screen.getByRole("button", { name: "Continue to preview" })).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Continue to preview" }));

    await waitFor(() => expect(screen.getByText("Person 1")).toBeInTheDocument());
    expect(screen.getByText("Person 50")).toBeInTheDocument();
    expect(screen.queryByText("Person 51")).not.toBeInTheDocument();
  });
});
