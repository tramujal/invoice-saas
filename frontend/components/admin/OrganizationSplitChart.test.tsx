import { describe, expect, it } from "vitest";

import type { PlatformBusinessMetrics } from "@/lib/types";
import { render, screen } from "@/tests/test-utils";

import { OrganizationSplitChart } from "./OrganizationSplitChart";

const business: PlatformBusinessMetrics = {
  organizations_total: 5,
  active_users_total: 8,
  paying_organizations: 2,
  trial_organizations: 1,
  mrr: "58.00",
  arr: "696.00",
  currency: "USD",
  churn_rate_30d: 0,
  conversion_rate_30d: 50,
  average_revenue_per_organization: "29.00",
};

describe("OrganizationSplitChart", () => {
  it("shows a loading skeleton", () => {
    const { container } = render(<OrganizationSplitChart data={null} loading />);
    expect(screen.getByText("Organizations by status")).toBeInTheDocument();
    expect(container.querySelector(".animate-pulse")).toBeInTheDocument();
  });

  it("shows an empty state when there are no organizations", () => {
    render(<OrganizationSplitChart data={{ ...business, organizations_total: 0 }} loading={false} />);
    expect(screen.getByText("No organizations yet.")).toBeInTheDocument();
  });

  it("shows an empty state when data is null", () => {
    render(<OrganizationSplitChart data={null} loading={false} />);
    expect(screen.getByText("No organizations yet.")).toBeInTheDocument();
  });

  it("renders the chart when data is present", () => {
    const { container } = render(<OrganizationSplitChart data={business} loading={false} />);
    expect(screen.queryByText("No organizations yet.")).not.toBeInTheDocument();
    expect(container.querySelector(".recharts-responsive-container")).toBeInTheDocument();
  });
});
