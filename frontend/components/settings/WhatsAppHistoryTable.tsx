"use client";

import { Badge } from "@/components/ui/Badge";
import {
  TABLE_BODY_CLASS,
  TABLE_CELL_CLASS,
  TABLE_CLASS,
  TABLE_HEAD_CELL_CLASS,
  TABLE_HEAD_CLASS,
  TABLE_ROW_CLASS,
  TABLE_WRAPPER_CLASS,
} from "@/components/ui/TableShell";
import { useTranslation } from "@/lib/i18n/useTranslation";
import type { WhatsAppCommandHistoryItemResponse } from "@/lib/types";

const STATUS_BADGE_CLASS: Record<string, string> = {
  processed: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  failed: "bg-red-50 text-red-700 ring-red-200",
  rejected: "bg-amber-50 text-amber-700 ring-amber-200",
};

function statusBadgeClass(status: string): string {
  return STATUS_BADGE_CLASS[status] ?? "bg-slate-100 text-slate-600 ring-slate-200";
}

function formatDateTime(value: string, locale: string): string {
  return new Date(value).toLocaleString(locale, { dateStyle: "medium", timeStyle: "short" });
}

type WhatsAppHistoryTableProps = {
  items: WhatsAppCommandHistoryItemResponse[] | null;
  loading: boolean;
};

/** Safe channel metadata only -- see WhatsAppCommandHistoryItemResponse's
 * own docstring: never message text, transcripts, or phone numbers,
 * which is why this table has no "content" column at all. settings.manage
 * only (the parent gates who ever fetches/renders this). */
export function WhatsAppHistoryTable({ items, loading }: WhatsAppHistoryTableProps) {
  const { t, language } = useTranslation();

  return (
    <section className="space-y-3">
      <div>
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">{t("whatsapp.historyTitle")}</h2>
        <p className="mt-1 text-sm text-slate-500">{t("whatsapp.historySubtitle")}</p>
      </div>
      <div className={TABLE_WRAPPER_CLASS}>
        <div className="overflow-x-auto">
          <table className={TABLE_CLASS}>
            <thead className={TABLE_HEAD_CLASS}>
              <tr>
                <th className={TABLE_HEAD_CELL_CLASS}>{t("whatsapp.colType")}</th>
                <th className={TABLE_HEAD_CELL_CLASS}>{t("whatsapp.colAction")}</th>
                <th className={TABLE_HEAD_CELL_CLASS}>{t("whatsapp.colStatus")}</th>
                <th className={TABLE_HEAD_CELL_CLASS}>{t("whatsapp.colWhen")}</th>
              </tr>
            </thead>
            <tbody className={TABLE_BODY_CLASS}>
              {loading ? (
                <tr>
                  <td className={TABLE_CELL_CLASS} colSpan={4}>
                    {t("whatsapp.historyLoading")}
                  </td>
                </tr>
              ) : !items || items.length === 0 ? (
                <tr>
                  <td className={TABLE_CELL_CLASS} colSpan={4}>
                    {t("whatsapp.historyEmptyState")}
                  </td>
                </tr>
              ) : (
                items.map((item) => (
                  <tr key={item.id} className={TABLE_ROW_CLASS}>
                    <td className={TABLE_CELL_CLASS}>
                      {item.message_type === "audio" ? t("whatsapp.typeAudio") : t("whatsapp.typeText")}
                    </td>
                    <td className={TABLE_CELL_CLASS}>{item.command_action ?? "—"}</td>
                    <td className={TABLE_CELL_CLASS}>
                      <Badge className={statusBadgeClass(item.status)}>{item.status}</Badge>
                    </td>
                    <td className={TABLE_CELL_CLASS}>{formatDateTime(item.created_at, language)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}
