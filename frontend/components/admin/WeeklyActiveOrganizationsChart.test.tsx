import { describe, expect, it } from "vitest";

import type { PlatformWeeklyActiveOrganizationsCount } from "@/lib/types";
import { render, screen } from "@/tests/test-utils";

import { WeeklyActiveOrganizationsChart } from "./WeeklyActiveOrganizationsChart";

const data: PlatformWeeklyActiveOrganizationsCount[] = [
  { week_start: "2026-07-20", count: 3 },
  { week_start: "2026-07-27", count: 4 },
];

describe("WeeklyActiveOrganizationsChart", () => {
  it("shows a loading skeleton", () => {
    const { container } = render(<WeeklyActiveOrganizationsChart data={[]} loading />);
    expect(screen.getByText("Weekly active organizations")).toBeInTheDocument();
    expect(container.querySelector(".animate-pulse")).toBeInTheDocument();
  });

  it("shows an empty state when there is no data", () => {
    render(<WeeklyActiveOrganizationsChart data={[]} loading={false} />);
    expect(screen.getByText("No organization activity in this period.")).toBeInTheDocument();
  });

  it("renders the chart when data is present", () => {
    const { container } = render(<WeeklyActiveOrganizationsChart data={data} loading={false} />);
    expect(screen.queryByText("No organization activity in this period.")).not.toBeInTheDocument();
    expect(container.querySelector(".recharts-responsive-container")).toBeInTheDocument();
  });
});
