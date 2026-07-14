"use client";

import { FormEvent, useState } from "react";

import { useToast } from "@/components/ui/toast";
import { apiFetch, orgPath } from "@/lib/api";
import { formatApiError, getApiErrorCode, isEmailNotVerifiedError } from "@/lib/format-api-error";
import { useTranslation } from "@/lib/i18n/useTranslation";
import { INVITATION_ROLES, getMembershipRoleLabel, type InvitationRole } from "@/lib/membership-role";
import type { Invitation } from "@/lib/types";

const EMAIL_MAX_LENGTH = 255;

function simpleEmailValid(email: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
}

type InviteMemberFormProps = {
  onInvited: () => void | Promise<void>;
};

export function InviteMemberForm({ onInvited }: InviteMemberFormProps) {
  const toast = useToast();
  const { t } = useTranslation();
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<InvitationRole>("member");
  const [emailError, setEmailError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();

    const trimmed = email.trim();
    if (!trimmed) {
      setEmailError(t("common.errorRequired", { field: t("common.email") }));
      return;
    }
    if (trimmed.length > EMAIL_MAX_LENGTH) {
      setEmailError(t("common.errorMaxLength", { field: t("common.email"), max: EMAIL_MAX_LENGTH }));
      return;
    }
    if (!simpleEmailValid(trimmed)) {
      setEmailError(t("common.errorInvalidEmail"));
      return;
    }
    setEmailError(null);

    const loadingId = toast.loading(t("team.toastInviting"));
    setIsSubmitting(true);
    try {
      await apiFetch<Invitation>(orgPath("invitations"), {
        method: "POST",
        body: JSON.stringify({ email: trimmed, role }),
      });
      toast.dismiss(loadingId);
      toast.success(t("team.toastInvited"));
      setEmail("");
      setRole("member");
      await onInvited();
    } catch (err) {
      toast.dismiss(loadingId);
      const code = getApiErrorCode(err);
      let message: string;
      if (isEmailNotVerifiedError(err)) {
        message = t("errors.emailNotVerified");
      } else if (code === "already_member") {
        message = t("team.errorAlreadyMember");
      } else if (code === "invitation_already_pending") {
        message = t("team.errorInvitationAlreadyPending");
      } else {
        message = formatApiError(err, t("team.toastInviteError"));
      }
      toast.error(message);
    } finally {
      setIsSubmitting(false);
    }
  }

  const disabled = isSubmitting;

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-6">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
        {t("team.inviteTitle")}
      </h2>
      <p className="mt-1 text-sm text-slate-500">{t("team.inviteSubtitle")}</p>

      <form onSubmit={(e) => void handleSubmit(e)} className="mt-4 flex flex-col gap-4 sm:flex-row sm:items-end" noValidate>
        <div className="flex-1">
          <label htmlFor="invite-email" className="text-sm font-medium text-slate-700">
            {t("common.email")} <span className="text-red-600">*</span>
          </label>
          <input
            id="invite-email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            disabled={disabled}
            maxLength={EMAIL_MAX_LENGTH}
            placeholder="teammate@example.com"
            className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none ring-slate-400 focus:ring-2 disabled:bg-slate-50"
            aria-invalid={Boolean(emailError)}
            aria-describedby={emailError ? "invite-email-err" : undefined}
          />
          {emailError ? (
            <p id="invite-email-err" className="mt-1 text-xs text-red-600" role="alert">
              {emailError}
            </p>
          ) : null}
        </div>

        <div>
          <label htmlFor="invite-role" className="text-sm font-medium text-slate-700">
            {t("team.roleLabel")}
          </label>
          <select
            id="invite-role"
            value={role}
            onChange={(e) => setRole(e.target.value as InvitationRole)}
            disabled={disabled}
            className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none ring-slate-400 focus:ring-2 disabled:bg-slate-50 sm:w-40"
          >
            {INVITATION_ROLES.map((r) => (
              <option key={r} value={r}>
                {getMembershipRoleLabel(t, r)}
              </option>
            ))}
          </select>
        </div>

        <button
          type="submit"
          disabled={disabled}
          className="inline-flex items-center justify-center gap-2 rounded-lg bg-slate-900 px-5 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-70"
        >
          {isSubmitting ? t("common.saving") : t("team.inviteButton")}
        </button>
      </form>
    </section>
  );
}
