"use client";

import { Badge } from "@/components/ui/Badge";
import { useTranslation } from "@/lib/i18n/useTranslation";
import type { ObservationSeverity, OverallHealth, RecommendationPriority } from "@/lib/types";

const HEALTH_BADGE_CLASS: Record<OverallHealth, string> = {
  excellent: "bg-emerald-100 text-emerald-900 ring-emerald-200/80",
  good: "bg-emerald-100 text-emerald-900 ring-emerald-200/80",
  fair: "bg-amber-100 text-amber-900 ring-amber-200/80",
  poor: "bg-orange-100 text-orange-900 ring-orange-200/80",
  critical: "bg-red-100 text-red-900 ring-red-200/80",
};

export function HealthBadge({ health }: { health: OverallHealth }) {
  const { t } = useTranslation();
  return <Badge className={HEALTH_BADGE_CLASS[health]}>{t(`financial.advisor.health.${health}`)}</Badge>;
}

const SEVERITY_BADGE_CLASS: Record<ObservationSeverity, string> = {
  info: "bg-slate-100 text-slate-700 ring-slate-200/80",
  positive: "bg-emerald-100 text-emerald-900 ring-emerald-200/80",
  warning: "bg-amber-100 text-amber-900 ring-amber-200/80",
  critical: "bg-red-100 text-red-900 ring-red-200/80",
};

export function SeverityBadge({ severity }: { severity: ObservationSeverity }) {
  const { t } = useTranslation();
  return <Badge className={SEVERITY_BADGE_CLASS[severity]}>{t(`financial.advisor.severity.${severity}`)}</Badge>;
}

const PRIORITY_BADGE_CLASS: Record<RecommendationPriority, string> = {
  low: "bg-slate-100 text-slate-700 ring-slate-200/80",
  medium: "bg-amber-100 text-amber-900 ring-amber-200/80",
  high: "bg-red-100 text-red-900 ring-red-200/80",
};

export function PriorityBadge({ priority }: { priority: RecommendationPriority }) {
  const { t } = useTranslation();
  return <Badge className={PRIORITY_BADGE_CLASS[priority]}>{t(`financial.advisor.priority.${priority}`)}</Badge>;
}
