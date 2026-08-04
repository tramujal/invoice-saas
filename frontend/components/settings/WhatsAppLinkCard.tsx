"use client";

import { FormEvent, useEffect, useState } from "react";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { useToast } from "@/components/ui/toast";
import { apiFetch, orgPath } from "@/lib/api";
import { formatApiError, isEmailNotVerifiedError } from "@/lib/format-api-error";
import { useTranslation } from "@/lib/i18n/useTranslation";
import type { WhatsAppIdentityResponse, WhatsAppIdentityStatus, WhatsAppLinkResponse } from "@/lib/types";

const STATUS_BADGE_CLASS: Record<WhatsAppIdentityStatus, string> = {
  pending: "bg-amber-50 text-amber-700 ring-amber-200",
  verified: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  disabled: "bg-slate-100 text-slate-500 ring-slate-200",
};

type WhatsAppLinkCardProps = {
  identity: WhatsAppIdentityResponse | null;
  canUseWhatsapp: boolean;
  onChanged: () => void;
};

/** Self-service link/revoke for the CALLER's own phone number only -- see
 * app/routers/whatsapp.py's POST .../link and .../me/revoke, which never
 * accept a target user, only ever act on current_user. Distinct from
 * WhatsAppIdentitiesTable, which is the settings.manage-gated org-wide
 * view over every OTHER user's mapping too. */
export function WhatsAppLinkCard({ identity, canUseWhatsapp, onChanged }: WhatsAppLinkCardProps) {
  const { t } = useTranslation();
  const toast = useToast();

  const [phone, setPhone] = useState("");
  const [phoneError, setPhoneError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [revoking, setRevoking] = useState(false);
  const [pendingLink, setPendingLink] = useState<WhatsAppLinkResponse | null>(null);

  // The identity this session just created for `pendingLink` starts out
  // `status: "pending"` -- a background refresh right after linking (see
  // onChanged() below) makes `identity` non-null well before the user has
  // had a chance to read/copy the one-time code, so the code stays the
  // priority view until verification actually completes, not just until
  // an identity row exists. Only cleared once the backend confirms the
  // code was used (identity.status flips to "verified").
  useEffect(() => {
    if (identity?.status === "verified" && pendingLink) {
      setPendingLink(null);
    }
  }, [identity?.status, pendingLink]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const trimmed = phone.trim();
    if (!trimmed) {
      setPhoneError(t("common.errorRequired", { field: t("whatsapp.phoneLabel") }));
      return;
    }
    setPhoneError(null);
    setSubmitting(true);
    try {
      const result = await apiFetch<WhatsAppLinkResponse>(orgPath("whatsapp/link"), {
        method: "POST",
        body: JSON.stringify({ phone_number: trimmed }),
      });
      setPendingLink(result);
      setPhone("");
      onChanged();
    } catch (err) {
      toast.error(
        isEmailNotVerifiedError(err) ? t("errors.emailNotVerified") : formatApiError(err, t("whatsapp.toastLinkError"))
      );
    } finally {
      setSubmitting(false);
    }
  }

  async function handleRevoke() {
    if (!window.confirm(t("whatsapp.confirmRevokeOwn"))) return;
    setRevoking(true);
    try {
      await apiFetch(orgPath("whatsapp/me/revoke"), { method: "POST" });
      toast.success(t("whatsapp.toastRevoked"));
      setPendingLink(null);
      onChanged();
    } catch (err) {
      toast.error(formatApiError(err, t("whatsapp.toastActionError")));
    } finally {
      setRevoking(false);
    }
  }

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-6">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">{t("whatsapp.linkTitle")}</h2>
      <p className="mt-1 text-sm text-slate-500">{t("whatsapp.linkSubtitle")}</p>

      {pendingLink ? (
        <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          <p className="font-medium">{t("whatsapp.pendingLinkTitle")}</p>
          <p className="mt-1">
            {t("whatsapp.pendingLinkInstructions", { phone: pendingLink.normalized_phone_number })}
          </p>
          <p className="mt-2 select-all font-mono text-lg font-semibold tracking-widest">
            {pendingLink.verification_code}
          </p>
          <Button
            type="button"
            variant="secondary"
            size="sm"
            className="mt-3"
            onClick={() => void handleRevoke()}
            loading={revoking}
          >
            {t("whatsapp.revokeOwnButton")}
          </Button>
        </div>
      ) : identity ? (
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
          <div>
            <div className="font-mono text-sm text-slate-900">{identity.normalized_phone_number}</div>
            <Badge className={`mt-1 ${STATUS_BADGE_CLASS[identity.status]}`}>
              {t(`whatsapp.identityStatus.${identity.status}`)}
            </Badge>
          </div>
          <Button type="button" variant="secondary" size="sm" onClick={() => void handleRevoke()} loading={revoking}>
            {t("whatsapp.revokeOwnButton")}
          </Button>
        </div>
      ) : (
        <form onSubmit={(e) => void handleSubmit(e)} className="mt-4 flex flex-wrap items-end gap-3" noValidate>
          <div className="min-w-0 flex-1">
            <label htmlFor="whatsapp-phone" className="text-sm font-medium text-slate-700">
              {t("whatsapp.phoneLabel")}
            </label>
            <Input
              id="whatsapp-phone"
              type="tel"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              disabled={submitting || !canUseWhatsapp}
              placeholder={t("whatsapp.phonePlaceholder")}
              className="mt-1"
              aria-invalid={Boolean(phoneError)}
              aria-describedby={phoneError ? "whatsapp-phone-err" : undefined}
            />
            {phoneError ? (
              <p id="whatsapp-phone-err" className="mt-1 text-xs text-red-600" role="alert">
                {phoneError}
              </p>
            ) : null}
          </div>
          <Button type="submit" disabled={submitting || !canUseWhatsapp} loading={submitting}>
            {t("whatsapp.linkButton")}
          </Button>
        </form>
      )}
    </section>
  );
}
