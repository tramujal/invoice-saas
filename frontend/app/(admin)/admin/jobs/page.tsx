"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { type JobActionMode, JobActionDialog } from "@/components/admin/JobActionDialog";
import { JobDetailDrawer } from "@/components/admin/JobDetailDrawer";
import { type ActiveFilterChip, FilterToolbar } from "@/components/ui/FilterToolbar";
import { Badge } from "@/components/ui/Badge";
import { RowActionsMenu, STICKY_ACTIONS_TD_CLASS, STICKY_ACTIONS_TH_CLASS } from "@/components/ui/RowActionsMenu";
import { Select } from "@/components/ui/Input";
import { PageContainer } from "@/components/ui/PageContainer";
import { PageHeader } from "@/components/ui/PageHeader";
import {
  TABLE_BODY_CLASS,
  TABLE_CELL_CLASS,
  TABLE_CLASS,
  TABLE_HEAD_CELL_CLASS,
  TABLE_HEAD_CLASS,
  TABLE_ROW_CLASS,
  TABLE_WRAPPER_CLASS,
} from "@/components/ui/TableShell";
import { useToast } from "@/components/ui/toast";
import { ApiError, apiFetch } from "@/lib/api";
import { useTranslation } from "@/lib/i18n/useTranslation";
import { BACKGROUND_JOB_STATUSES, getJobStatusLabel, getJobTypeLabel, JOB_STATUS_BADGE_CLASS, JOB_TYPES } from "@/lib/job-status";
import type {
  BackgroundJobStatus,
  PaginatedPlatformBackgroundJobsResponse,
  PlatformBackgroundJobDetail,
  PlatformBackgroundJobEntry,
} from "@/lib/types";
import { useDebouncedValue } from "@/lib/use-debounced-value";

const GENERIC_LOAD_ERROR = "__generic_load_error__";
const pageSize = 20;

const CANCELLABLE_STATUSES: readonly BackgroundJobStatus[] = ["pending", "retry_scheduled"];
const RETRYABLE_STATUSES: readonly BackgroundJobStatus[] = ["permanently_failed", "cancelled"];

function formatTimestamp(value: string | null, locale: string): string {
  if (!value) return "—";
  return new Date(value).toLocaleString(locale, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function PlatformJobsPage() {
  const { t, language } = useTranslation();
  const toast = useToast();
  const [data, setData] = useState<PaginatedPlatformBackgroundJobsResponse | null>(null);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [orgSearch, setOrgSearch] = useState("");
  const debouncedOrgSearch = useDebouncedValue(orgSearch, 300);
  const [statusFilter, setStatusFilter] = useState<string>("any");
  const [jobTypeFilter, setJobTypeFilter] = useState<string>("any");
  const abortRef = useRef<AbortController | null>(null);

  const [selectedJob, setSelectedJob] = useState<PlatformBackgroundJobDetail | null>(null);
  const [actionTarget, setActionTarget] = useState<PlatformBackgroundJobEntry | null>(null);
  const [actionMode, setActionMode] = useState<JobActionMode | null>(null);
  const [actionSubmitting, setActionSubmitting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const hasActiveFilters =
    debouncedOrgSearch.trim() !== "" || statusFilter !== "any" || jobTypeFilter !== "any";
  const isDefaultState = !hasActiveFilters;

  const filterChips: ActiveFilterChip[] = [];
  if (statusFilter !== "any") {
    const label = `${t("jobs.filterStatusLabel")}: ${getJobStatusLabel(t, statusFilter as BackgroundJobStatus)}`;
    filterChips.push({
      key: "status",
      label,
      removeLabel: t("common.removeFilter", { label }),
      onRemove: () => resetToFirstPage(setStatusFilter)("any"),
    });
  }
  if (jobTypeFilter !== "any") {
    const label = `${t("jobs.filterJobTypeLabel")}: ${getJobTypeLabel(t, jobTypeFilter)}`;
    filterChips.push({
      key: "jobType",
      label,
      removeLabel: t("common.removeFilter", { label }),
      onRemove: () => resetToFirstPage(setJobTypeFilter)("any"),
    });
  }

  function resetToFirstPage<T>(setter: (v: T) => void) {
    return (value: T) => {
      setter(value);
      setOffset(0);
    };
  }

  function resetFilters() {
    setOrgSearch("");
    setStatusFilter("any");
    setJobTypeFilter("any");
    setOffset(0);
  }

  const load = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);
    setError(null);
    try {
      const q = new URLSearchParams({ limit: String(pageSize), offset: String(offset) });
      if (statusFilter !== "any") q.set("status", statusFilter);
      if (jobTypeFilter !== "any") q.set("job_type", jobTypeFilter);
      if (debouncedOrgSearch.trim()) q.set("organization_id", debouncedOrgSearch.trim());

      const json = await apiFetch<PaginatedPlatformBackgroundJobsResponse>(`/admin/jobs?${q.toString()}`, {
        signal: controller.signal,
      });
      setData(json);
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") return;
      setData(null);
      setError(e instanceof ApiError ? e.message : GENERIC_LOAD_ERROR);
    } finally {
      if (abortRef.current === controller) setLoading(false);
    }
  }, [offset, statusFilter, jobTypeFilter, debouncedOrgSearch]);

  useEffect(() => {
    void load();
    return () => abortRef.current?.abort();
  }, [load]);

  async function openDetail(jobId: string) {
    try {
      const detail = await apiFetch<PlatformBackgroundJobDetail>(`/admin/jobs/${jobId}`);
      setSelectedJob(detail);
    } catch {
      toast.error(t("jobs.loadError"));
    }
  }

  function openAction(job: PlatformBackgroundJobEntry, mode: JobActionMode) {
    setActionTarget(job);
    setActionMode(mode);
    setActionError(null);
  }

  function closeAction() {
    if (actionSubmitting) return;
    setActionTarget(null);
    setActionMode(null);
    setActionError(null);
  }

  async function handleConfirmAction(reason: string) {
    if (!actionTarget || !actionMode) return;
    setActionSubmitting(true);
    setActionError(null);
    try {
      await apiFetch<PlatformBackgroundJobEntry>(`/admin/jobs/${actionTarget.id}/${actionMode}`, {
        method: "POST",
        body: JSON.stringify({ reason }),
      });
      setActionTarget(null);
      setActionMode(null);
      toast.success(actionMode === "retry" ? t("jobs.retrySuccessToast") : t("jobs.cancelSuccessToast"));
      void load();
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : t("admin.mutationErrorGeneric"));
    } finally {
      setActionSubmitting(false);
    }
  }

  const totalPages = data ? Math.max(1, Math.ceil(data.total / pageSize)) : 1;
  const currentPage = Math.floor(offset / pageSize) + 1;
  const showEmpty = !loading && data !== null && data.items.length === 0;

  return (
    <PageContainer>
      <PageHeader title={t("jobs.title")} subtitle={t("jobs.subtitle")} />

      <FilterToolbar
        searchValue={orgSearch}
        onSearchChange={resetToFirstPage(setOrgSearch)}
        searchPlaceholder={t("jobs.searchPlaceholder")}
        searchAriaLabel={t("jobs.searchAriaLabel")}
        onReset={resetFilters}
        resetLabel={t("invoices.resetFilters")}
        isDefaultState={isDefaultState}
        filtersLabel={t("common.filters")}
        chips={filterChips}
      >
        <Select
          value={statusFilter}
          onChange={(e) => resetToFirstPage(setStatusFilter)(e.target.value)}
          fullWidth={false}
          aria-label={t("jobs.filterStatusLabel")}
        >
          <option value="any">{t("jobs.filterStatusLabel")}</option>
          {BACKGROUND_JOB_STATUSES.map((status) => (
            <option key={status} value={status}>
              {getJobStatusLabel(t, status)}
            </option>
          ))}
        </Select>
        <Select
          value={jobTypeFilter}
          onChange={(e) => resetToFirstPage(setJobTypeFilter)(e.target.value)}
          fullWidth={false}
          aria-label={t("jobs.filterJobTypeLabel")}
        >
          <option value="any">{t("jobs.filterJobTypeLabel")}</option>
          {JOB_TYPES.map((jobType) => (
            <option key={jobType} value={jobType}>
              {getJobTypeLabel(t, jobType)}
            </option>
          ))}
        </Select>
      </FilterToolbar>

      {error ? (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800" role="alert">
          {error === GENERIC_LOAD_ERROR ? t("jobs.loadError") : error}
        </div>
      ) : null}

      <div className={TABLE_WRAPPER_CLASS}>
        <div className="overflow-x-auto">
          <table className={TABLE_CLASS}>
            <thead className={TABLE_HEAD_CLASS}>
              <tr>
                <th className={TABLE_HEAD_CELL_CLASS}>{t("jobs.colJobType")}</th>
                <th className={TABLE_HEAD_CELL_CLASS}>{t("jobs.colStatus")}</th>
                <th className={TABLE_HEAD_CELL_CLASS}>{t("jobs.colOrganization")}</th>
                <th className={`hidden sm:table-cell ${TABLE_HEAD_CELL_CLASS}`}>{t("jobs.colAttempts")}</th>
                <th className={`hidden lg:table-cell ${TABLE_HEAD_CELL_CLASS}`}>{t("jobs.colAvailableAt")}</th>
                <th className={`hidden md:table-cell ${TABLE_HEAD_CELL_CLASS}`}>{t("jobs.colCreatedAt")}</th>
                <th className={STICKY_ACTIONS_TH_CLASS}>
                  <span className="sr-only">{t("common.moreActions")}</span>
                </th>
              </tr>
            </thead>
            <tbody className={TABLE_BODY_CLASS}>
              {loading ? (
                <tr>
                  <td colSpan={7} className={`text-center text-slate-500 ${TABLE_CELL_CLASS}`}>
                    {t("jobs.loading")}
                  </td>
                </tr>
              ) : showEmpty ? (
                <tr>
                  <td colSpan={7} className={TABLE_CELL_CLASS}>
                    {hasActiveFilters ? (
                      <div className="py-6 text-center">
                        <p className="text-sm font-medium text-slate-700">{t("jobs.emptyFilteredTitle")}</p>
                        <p className="mt-1 text-sm text-slate-500">{t("jobs.emptyFilteredDescription")}</p>
                        <button
                          type="button"
                          onClick={resetFilters}
                          className="mt-2 text-sm font-medium text-slate-700 underline hover:text-slate-900"
                        >
                          {t("invoices.resetFilters")}
                        </button>
                      </div>
                    ) : (
                      <div className="py-6 text-center">
                        <p className="text-sm font-medium text-slate-700">{t("jobs.emptyTitle")}</p>
                        <p className="mt-1 text-sm text-slate-500">{t("jobs.emptyDescription")}</p>
                      </div>
                    )}
                  </td>
                </tr>
              ) : (
                data?.items.map((job) => (
                  <tr key={job.id} className={`group ${TABLE_ROW_CLASS}`}>
                    <td className={TABLE_CELL_CLASS} title={job.job_type}>
                      {getJobTypeLabel(t, job.job_type)}
                    </td>
                    <td className={TABLE_CELL_CLASS}>
                      <Badge className={JOB_STATUS_BADGE_CLASS[job.status]}>{getJobStatusLabel(t, job.status)}</Badge>
                    </td>
                    <td className={`max-w-[160px] truncate ${TABLE_CELL_CLASS}`} title={job.organization_id ?? ""}>
                      {job.organization_id ?? "—"}
                    </td>
                    <td className={`hidden sm:table-cell ${TABLE_CELL_CLASS}`}>
                      {job.attempts} / {job.max_attempts}
                    </td>
                    <td className={`hidden lg:table-cell ${TABLE_CELL_CLASS}`}>
                      {formatTimestamp(job.available_at, language)}
                    </td>
                    <td className={`hidden md:table-cell ${TABLE_CELL_CLASS}`}>
                      {formatTimestamp(job.created_at, language)}
                    </td>
                    <td className={STICKY_ACTIONS_TD_CLASS}>
                      <RowActionsMenu label={t("common.moreActions")}>
                        <RowActionsMenu.Item onSelect={() => void openDetail(job.id)}>
                          {t("jobs.viewDetails")}
                        </RowActionsMenu.Item>
                        <RowActionsMenu.Item
                          onSelect={() => openAction(job, "retry")}
                          disabled={!RETRYABLE_STATUSES.includes(job.status)}
                          title={
                            RETRYABLE_STATUSES.includes(job.status) ? undefined : t("jobs.retryUnavailableHint")
                          }
                        >
                          {t("jobs.retryAction")}
                        </RowActionsMenu.Item>
                        <RowActionsMenu.Item
                          onSelect={() => openAction(job, "cancel")}
                          disabled={!CANCELLABLE_STATUSES.includes(job.status)}
                          destructive
                          title={
                            CANCELLABLE_STATUSES.includes(job.status) ? undefined : t("jobs.cancelUnavailableHint")
                          }
                        >
                          {t("jobs.cancelAction")}
                        </RowActionsMenu.Item>
                      </RowActionsMenu>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
        {data && data.total > pageSize ? (
          <div className="flex flex-col gap-3 border-t border-slate-100 px-4 py-3 text-sm text-slate-600 sm:flex-row sm:items-center sm:justify-between sm:px-6">
            <span>{t("invoices.pagination", { page: currentPage, totalPages, total: data.total })}</span>
            <div className="flex gap-2">
              <button
                type="button"
                disabled={offset === 0 || loading}
                onClick={() => setOffset((o) => Math.max(0, o - pageSize))}
                className="rounded-lg border border-slate-200 px-3 py-1.5 font-medium hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {t("invoices.previous")}
              </button>
              <button
                type="button"
                disabled={offset + pageSize >= data.total || loading}
                onClick={() => setOffset((o) => o + pageSize)}
                className="rounded-lg border border-slate-200 px-3 py-1.5 font-medium hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {t("invoices.next")}
              </button>
            </div>
          </div>
        ) : null}
      </div>

      <JobDetailDrawer
        job={selectedJob}
        onClose={() => setSelectedJob(null)}
        formatTimestamp={(value) => formatTimestamp(value, language)}
      />

      <JobActionDialog
        open={actionMode !== null}
        mode={actionMode ?? "retry"}
        submitting={actionSubmitting}
        error={actionError}
        onClose={closeAction}
        onConfirm={(reason) => void handleConfirmAction(reason)}
      />
    </PageContainer>
  );
}
