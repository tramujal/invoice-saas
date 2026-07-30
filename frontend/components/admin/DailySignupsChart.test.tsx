import { describe, expect, it } from "vitest";

import type { PlatformDailySignupCount } from "@/lib/types";
import { render, screen } from "@/tests/test-utils";

import { DailySignupsChart } from "./DailySignupsChart";

const data: PlatformDailySignupCount[] = [
  { day: "2026-07-28", count: 2 },
  { day: "2026-07-29", count: 5 },
];

describe("DailySignupsChart", () => {
  it("shows a loading skeleton", () => {
    const { container } = render(<DailySignupsChart data={[]} loading />);
    expect(screen.getByText("Daily signups (30d)")).toBeInTheDocument();
    expect(container.querySelector(".animate-pulse")).toBeInTheDocument();
  });

  it("shows an empty state when there is no data", () => {
    render(<DailySignupsChart data={[]} loading={false} />);
    expect(screen.getByText("No new organizations in this period.")).toBeInTheDocument();
  });

  it("renders the chart when data is present", () => {
    const { container } = render(<DailySignupsChart data={data} loading={false} />);
    expect(screen.queryByText("No new organizations in this period.")).not.toBeInTheDocument();
    expect(container.querySelector(".recharts-responsive-container")).toBeInTheDocument();
  });
});
