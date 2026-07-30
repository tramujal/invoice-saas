import { describe, expect, it } from "vitest";

import type { PlatformFeatureAdoption } from "@/lib/types";
import { render, screen } from "@/tests/test-utils";

import { FeatureAdoptionChart } from "./FeatureAdoptionChart";

const data: PlatformFeatureAdoption[] = [
  { feature: "ai_enabled", adopted_paying_organizations: 2, adopted_percent: 50 },
  { feature: "analytics_enabled", adopted_paying_organizations: 1, adopted_percent: 25 },
];

describe("FeatureAdoptionChart", () => {
  it("shows a loading skeleton", () => {
    const { container } = render(<FeatureAdoptionChart data={[]} loading />);
    expect(screen.getByText("Feature adoption (paying organizations)")).toBeInTheDocument();
    expect(container.querySelector(".animate-pulse")).toBeInTheDocument();
  });

  it("shows an empty state when there is no adoption data", () => {
    render(<FeatureAdoptionChart data={[]} loading={false} />);
    expect(screen.getByText("No paying organizations yet.")).toBeInTheDocument();
  });

  it("shows an empty state when every feature has zero adoption", () => {
    render(
      <FeatureAdoptionChart
        data={[{ feature: "ai_enabled", adopted_paying_organizations: 0, adopted_percent: 0 }]}
        loading={false}
      />
    );
    expect(screen.getByText("No paying organizations yet.")).toBeInTheDocument();
  });

  it("renders the chart and translates known feature keys", () => {
    const { container } = render(<FeatureAdoptionChart data={data} loading={false} />);
    expect(screen.queryByText("No paying organizations yet.")).not.toBeInTheDocument();
    expect(container.querySelector(".recharts-responsive-container")).toBeInTheDocument();
  });
});
