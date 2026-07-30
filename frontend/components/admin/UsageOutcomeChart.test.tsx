import { describe, expect, it } from "vitest";

import type { PlatformUsageMetrics } from "@/lib/types";
import { render, screen } from "@/tests/test-utils";

import { UsageOutcomeChart } from "./UsageOutcomeChart";

const usage: PlatformUsageMetrics = {
  ai_requests_30d: 12,
  api_keys_active: 3,
  api_keys_used_7d: 1,
  webhook_deliveries_30d: 4,
  webhook_deliveries_succeeded_30d: 3,
  webhook_deliveries_failed_30d: 1,
  background_jobs_30d: 20,
  background_jobs_succeeded_30d: 18,
  background_jobs_failed_30d: 2,
  emails_sent_30d: 9,
  notifications_created_30d: 14,
};

describe("UsageOutcomeChart", () => {
  it("shows a loading skeleton", () => {
    const { container } = render(<UsageOutcomeChart data={null} loading />);
    expect(screen.getByText("Job & delivery outcomes (30d)")).toBeInTheDocument();
    expect(container.querySelector(".animate-pulse")).toBeInTheDocument();
  });

  it("shows an empty state when there are no jobs or deliveries", () => {
    render(
      <UsageOutcomeChart
        data={{
          ...usage,
          background_jobs_succeeded_30d: 0,
          background_jobs_failed_30d: 0,
          webhook_deliveries_succeeded_30d: 0,
          webhook_deliveries_failed_30d: 0,
        }}
        loading={false}
      />
    );
    expect(screen.getByText("No jobs or deliveries in the last 30 days.")).toBeInTheDocument();
  });

  it("shows an empty state when data is null", () => {
    render(<UsageOutcomeChart data={null} loading={false} />);
    expect(screen.getByText("No jobs or deliveries in the last 30 days.")).toBeInTheDocument();
  });

  it("renders the chart when data is present", () => {
    const { container } = render(<UsageOutcomeChart data={usage} loading={false} />);
    expect(screen.queryByText("No jobs or deliveries in the last 30 days.")).not.toBeInTheDocument();
    expect(container.querySelector(".recharts-responsive-container")).toBeInTheDocument();
  });
});
