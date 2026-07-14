import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import type { AssistantChatMessage } from "@/lib/types";
import { renderWithProviders, screen } from "@/tests/test-utils";

import { ActionProposalCard } from "./ActionProposalCard";

const confirmMock = vi.fn();
const cancelMock = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    confirmAssistantAction: (...args: unknown[]) => confirmMock(...args),
    cancelAssistantAction: (...args: unknown[]) => cancelMock(...args),
  };
});

type ProposalMessage = Extract<AssistantChatMessage, { kind: "proposal" }>;

function baseMessage(overrides: Partial<ProposalMessage> = {}): ProposalMessage {
  return {
    kind: "proposal",
    proposalId: "proposal-1",
    action: "update_invoice_status",
    summary: { invoice_number: "INV-000001", old_status: "pending", new_status: "paid" },
    expiresAt: new Date(Date.now() + 60_000).toISOString(),
    status: "pending",
    ...overrides,
  };
}

function Harness({ initial }: { initial: ProposalMessage }) {
  const [message, setMessage] = useState(initial);
  return (
    <ActionProposalCard
      message={message}
      onStateChange={(patch: Partial<ProposalMessage>) =>
        setMessage((prev: ProposalMessage) => ({ ...prev, ...patch }))
      }
    />
  );
}

beforeEach(() => {
  confirmMock.mockReset();
  cancelMock.mockReset();
});

describe("ActionProposalCard", () => {
  it("confirms successfully and becomes terminal (executed)", async () => {
    confirmMock.mockResolvedValue({ status: "executed", action: "update_invoice_status", summary: {} });
    const user = userEvent.setup();
    renderWithProviders(<Harness initial={baseMessage()} />);

    await user.click(screen.getByRole("button", { name: "Confirm change" }));

    expect(await screen.findByText("Done")).toBeInTheDocument();
    expect(confirmMock).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: "Confirm change" })).not.toBeInTheDocument();
  });

  it("cancels successfully and becomes terminal (cancelled)", async () => {
    cancelMock.mockResolvedValue({ status: "cancelled" });
    const user = userEvent.setup();
    renderWithProviders(<Harness initial={baseMessage()} />);

    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(await screen.findByText("Cancelled")).toBeInTheDocument();
    expect(cancelMock).toHaveBeenCalledTimes(1);
  });

  it("a failed confirm shows an error state and disables further confirm attempts", async () => {
    confirmMock.mockRejectedValue(new ApiError("boom", 502));
    const user = userEvent.setup();
    renderWithProviders(<Harness initial={baseMessage()} />);

    await user.click(screen.getByRole("button", { name: "Confirm change" }));

    expect(await screen.findByText("Failed")).toBeInTheDocument();
    // The card is now terminal -- no confirm/cancel buttons remain, so a
    // second confirm attempt (double-click, or retry) is structurally
    // impossible from this card.
    expect(screen.queryByRole("button", { name: "Confirm change" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel" })).not.toBeInTheDocument();
  });

  it("already-terminal proposals (e.g. executed on load) render no action buttons at all", () => {
    renderWithProviders(<Harness initial={baseMessage({ status: "executed" })} />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("buttons are disabled while a confirm request is in flight", async () => {
    let resolveConfirm: (value: unknown) => void = () => {};
    confirmMock.mockReturnValue(
      new Promise((resolve) => {
        resolveConfirm = resolve;
      })
    );
    const user = userEvent.setup();
    renderWithProviders(<Harness initial={baseMessage()} />);

    const confirmButton = screen.getByRole("button", { name: "Confirm change" });
    await user.click(confirmButton);

    expect(screen.getByRole("button", { name: "Confirming…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();

    resolveConfirm({ status: "executed", action: "update_invoice_status", summary: {} });
    await screen.findByText("Done");
  });
});
