"use client";

import Link from "next/link";

import { DashboardCard } from "@/components/dashboard/DashboardCard";
import { getMembershipRoleLabel } from "@/lib/membership-role";
import { useTranslation } from "@/lib/i18n/useTranslation";
import type { TeamSummary } from "@/lib/types";

type TeamWidgetProps = {
  team: TeamSummary | null;
  loading?: boolean;
};

/** Mirrors QuotePipelineCard's shape exactly -- a 3-stat row plus a "view
 * all" link to the feature's own page. Team composition is independent of
 * invoicing activity, so this renders unconditionally on the dashboard
 * page, same as QuotePipelineCard, rather than being suppressed by the
 * invoice-only empty state. */
export function TeamWidget({ team, loading = false }: TeamWidgetProps) {
  const { t } = useTranslation();

  return (
    <section aria-label={t("dashboard.teamWidgetTitle")} className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <h2 className="text-lg font-semibold text-slate-900">{t("dashboard.teamWidgetTitle")}</h2>
        <Link href="/settings/team" className="text-sm font-medium text-slate-700 hover:text-slate-900">
          {t("dashboard.viewAll")}
        </Link>
      </div>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <DashboardCard
          title={t("dashboard.teamTotalMembersLabel")}
          value={team ? String(team.total_members) : "—"}
          loading={loading}
        />
        <DashboardCard
          title={t("dashboard.teamPendingInvitationsLabel")}
          value={team ? String(team.pending_invitations) : "—"}
          loading={loading}
        />
        <DashboardCard
          title={t("dashboard.teamByRoleLabel")}
          value={
            team
              ? team.by_role
                  .filter((row) => row.count > 0)
                  .map((row) => `${row.count} ${getMembershipRoleLabel(t, row.role)}`)
                  .join(", ") || "—"
              : "—"
          }
          loading={loading}
        />
      </div>
    </section>
  );
}
