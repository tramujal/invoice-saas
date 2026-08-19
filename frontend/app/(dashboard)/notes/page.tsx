"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { NoteStatusBadge, NoteTypeBadge, signedAmountPrefix } from "@/components/notes/NoteBadges";
import { EmptyState } from "@/components/ui/EmptyState";
import { Select } from "@/components/ui/Input";
import { PageContainer } from "@/components/ui/PageContainer";
import { PageHeader } from "@/components/ui/PageHeader";
import { Skeleton } from "@/components/ui/Skeleton";
import {
  TABLE_BODY_CLASS,
  TABLE_CELL_CLASS,
  TABLE_CLASS,
  TABLE_HEAD_CELL_CLASS,
  TABLE_HEAD_CLASS,
  TABLE_ROW_CLASS,
  TABLE_WRAPPER_CLASS,
} from "@/components/ui/TableShell";
import { apiFetch, orgPath } from "@/lib/api";
import { formatApiError } from "@/lib/format-api-error";
import { useTranslation } from "@/lib/i18n/useTranslation";
import { formatCurrency } from "@/lib/money";
import type {
  AdjustmentNoteStatus,
  AdjustmentNoteType,
  PaginatedAdjustmentNotes,
} from "@/lib/types";

/** One unified "Credit & Debit Notes" list (Phase 29).
 *
 * A single page rather than two, because splitting by type would
 * duplicate every column, filter and empty state to express one enum --
 * exactly the reasoning the backend already applied to the API and the
 * domain model. `type` is just another filter here.
 */
export default function AdjustmentNotesListPage() {
  const { t } = useTranslation();
  const [data, setData] = useState<PaginatedAdjustmentNotes | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [typeFilter, setTypeFilter] = useState<AdjustmentNoteType | "all">("all");
  const [statusFilter, setStatusFilter] = useState<AdjustmentNoteStatus | "all">("all");
  const [search, setSearch] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    const params = new URLSearchParams();
    if (typeFilter !== "all") params.set("note_type", typeFilter);
    if (statusFilter !== "all") params.set("status", statusFilter);
    try {
      const result = await apiFetch<PaginatedAdjustmentNotes>(
        orgPath(`adjustment-notes?${params.toString()}`)
      );
      setData(result);
    } catch (err) {
      setError(formatApiError(err, t("notes.listLoadError")));
    } finally {
      setLoading(false);
    }
  }, [typeFilter, statusFilter]); // eslint-disable-line react-hooks/exhaustive-deps -- t() is not memoized; including it re-triggers the fetch on every render

  useEffect(() => {
    void load();
  }, [load]);

  const items = (data?.items ?? []).filter((note) => {
    if (!search.trim()) return true;
    const term = search.trim().toLowerCase();
    return (
      note.note_number.toLowerCase().includes(term) ||
      (note.customer_name ?? "").toLowerCase().includes(term)
    );
  });

  return (
    <PageContainer width="wide" spacing="8" className="pb-12">
      <PageHeader title={t("notes.listTitle")} subtitle={t("notes.listSubtitle")} />

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <input
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={t("notes.searchPlaceholder")}
          aria-label={t("notes.searchPlaceholder")}
          className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm shadow-sm sm:max-w-xs"
        />
        <Select
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value as AdjustmentNoteType | "all")}
          className="sm:w-48"
        >
          <option value="all">{t("notes.filterAllTypes")}</option>
          <option value="credit">{t("notes.type.credit")}</option>
          <option value="debit">{t("notes.type.debit")}</option>
        </Select>
        <Select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as AdjustmentNoteStatus | "all")}
          className="sm:w-48"
        >
          <option value="all">{t("notes.filterAllStatuses")}</option>
          <option value="draft">{t("notes.status.draft")}</option>
          <option value="issued">{t("notes.status.issued")}</option>
          <option value="void">{t("notes.status.void")}</option>
        </Select>
      </div>

      {loading ? (
        <div className="space-y-2">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </div>
      ) : error ? (
        <EmptyState title={t("notes.listLoadErrorTitle")} description={error} />
      ) : items.length === 0 ? (
        <EmptyState title={t("notes.emptyTitle")} description={t("notes.emptyBody")} />
      ) : (
        <div className={`${TABLE_WRAPPER_CLASS} overflow-x-auto`}>
          <table className={TABLE_CLASS}>
            <thead className={TABLE_HEAD_CLASS}>
              <tr>
                <th className={TABLE_HEAD_CELL_CLASS}>{t("notes.colNumber")}</th>
                <th className={TABLE_HEAD_CELL_CLASS}>{t("notes.colType")}</th>
                <th className={TABLE_HEAD_CELL_CLASS}>{t("notes.colCustomer")}</th>
                <th className={TABLE_HEAD_CELL_CLASS}>{t("notes.colStatus")}</th>
                <th className={TABLE_HEAD_CELL_CLASS}>{t("notes.colIssueDate")}</th>
                <th className={`${TABLE_HEAD_CELL_CLASS} text-right`}>{t("notes.colTotal")}</th>
              </tr>
            </thead>
            <tbody className={TABLE_BODY_CLASS}>
              {items.map((note) => (
                <tr key={note.id} className={TABLE_ROW_CLASS}>
                  <td className={TABLE_CELL_CLASS}>
                    <Link
                      href={`/notes/${note.id}`}
                      className="font-medium text-slate-900 hover:underline"
                    >
                      {note.note_number}
                    </Link>
                  </td>
                  <td className={TABLE_CELL_CLASS}>
                    <NoteTypeBadge noteType={note.note_type} />
                  </td>
                  <td className={TABLE_CELL_CLASS}>{note.customer_name ?? "—"}</td>
                  <td className={TABLE_CELL_CLASS}>
                    <NoteStatusBadge status={note.status} />
                  </td>
                  <td className={TABLE_CELL_CLASS}>{note.issue_date ?? "—"}</td>
                  <td
                    className={`${TABLE_CELL_CLASS} text-right font-medium ${
                      note.note_type === "credit" ? "text-rose-700" : "text-sky-700"
                    }`}
                  >
                    {signedAmountPrefix(note.note_type)}
                    {formatCurrency(Number(note.total), note.currency_code)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </PageContainer>
  );
}
