"use client";

import { useState } from "react";

import { Badge } from "@/components/ui/Badge";
import {
  RowActionsMenu,
  STICKY_ACTIONS_TD_CLASS,
  STICKY_ACTIONS_TH_CLASS,
} from "@/components/ui/RowActionsMenu";
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
import { apiFetch, orgPath } from "@/lib/api";
import { formatApiError } from "@/lib/format-api-error";
import { useTranslation } from "@/lib/i18n/useTranslation";
import type { WhatsAppIdentityResponse, WhatsAppIdentityStatus } from "@/lib/types";

const STATUS_BADGE_CLASS: Record<WhatsAppIdentityStatus, string> = {
  pending: "bg-amber-50 text-amber-700 ring-amber-200",
  verified: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  disabled: "bg-slate-100 text-slate-500 ring-slate-200",
};

function formatDateTime(value: string | null, locale: string): string {
  if (!value) return "—";
  return new Date(value).toLocaleString(locale, { dateStyle: "medium", timeStyle: "short" });
}

type WhatsAppIdentitiesTableProps = {
  identities: WhatsAppIdentityResponse[] | null;
  loading: boolean;
  onChanged: () => void;
};

/** Org-wide linked-number view -- requires settings.manage (the parent
 * only ever fetches/renders this for callers with that permission; see
 * app/routers/whatsapp.py's GET .../identities and POST
 * .../identities/{id}/revoke, both permission-gated server-side too). */
export function WhatsAppIdentitiesTable({ identities, loading, onChanged }: WhatsAppIdentitiesTableProps) {
  const { t, language } = useTranslation();
  const toast = useToast();
  const [busyId, setBusyId] = useState<string | null>(null);

  async function handleRevoke(identity: WhatsAppIdentityResponse) {
    if (!window.confirm(t("whatsapp.confirmRevokeIdentity", { phone: identity.normalized_phone_number }))) return;
    setBusyId(identity.id);
    try {
      await apiFetch(orgPath(`whatsapp/identities/${identity.id}/revoke`), { method: "POST" });
      toast.success(t("whatsapp.toastRevoked"));
      onChanged();
    } catch (err) {
      toast.error(formatApiError(err, t("whatsapp.toastActionError")));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <section className="space-y-3">
      <div>
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">{t("whatsapp.identitiesTitle")}</h2>
        <p className="mt-1 text-sm text-slate-500">{t("whatsapp.identitiesSubtitle")}</p>
      </div>
      <div className={TABLE_WRAPPER_CLASS}>
        <div className="overflow-x-auto">
          <table className={TABLE_CLASS}>
            <thead className={TABLE_HEAD_CLASS}>
              <tr>
                <th className={TABLE_HEAD_CELL_CLASS}>{t("whatsapp.colUser")}</th>
                <th className={TABLE_HEAD_CELL_CLASS}>{t("whatsapp.colPhone")}</th>
                <th className={TABLE_HEAD_CELL_CLASS}>{t("whatsapp.colStatus")}</th>
                <th className={TABLE_HEAD_CELL_CLASS}>{t("whatsapp.colLastMessage")}</th>
                <th className={STICKY_ACTIONS_TH_CLASS}>{t("common.moreActions")}</th>
              </tr>
            </thead>
            <tbody className={TABLE_BODY_CLASS}>
              {loading ? (
                <tr>
                  <td className={TABLE_CELL_CLASS} colSpan={5}>
                    {t("whatsapp.identitiesLoading")}
                  </td>
                </tr>
              ) : !identities || identities.length === 0 ? (
                <tr>
                  <td className={TABLE_CELL_CLASS} colSpan={5}>
                    {t("whatsapp.identitiesEmptyState")}
                  </td>
                </tr>
              ) : (
                identities.map((identity) => (
                  <tr key={identity.id} className={TABLE_ROW_CLASS}>
                    <td className={TABLE_CELL_CLASS}>{identity.user_email}</td>
                    <td className={TABLE_CELL_CLASS}>
                      <span className="font-mono text-xs text-slate-600">{identity.normalized_phone_number}</span>
                    </td>
                    <td className={TABLE_CELL_CLASS}>
                      <Badge className={STATUS_BADGE_CLASS[identity.status]}>
                        {t(`whatsapp.identityStatus.${identity.status}`)}
                      </Badge>
                    </td>
                    <td className={TABLE_CELL_CLASS}>{formatDateTime(identity.last_message_at, language)}</td>
                    <td className={STICKY_ACTIONS_TD_CLASS}>
                      <RowActionsMenu label={t("common.moreActions")}>
                        <RowActionsMenu.Item
                          disabled={busyId === identity.id || identity.status === "disabled"}
                          onSelect={() => void handleRevoke(identity)}
                        >
                          {t("whatsapp.revokeAction")}
                        </RowActionsMenu.Item>
                      </RowActionsMenu>
                    </td>
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
