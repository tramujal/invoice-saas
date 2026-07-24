"use client";

import { FormEvent, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Input, Select } from "@/components/ui/Input";
import { PlanLimitReachedDialog } from "@/components/ui/PlanLimitReachedDialog";
import { useToast } from "@/components/ui/toast";
import { apiFetch, orgPath } from "@/lib/api";
import {
  formatApiError,
  getApiErrorCode,
  getPlanLimitReachedDetail,
  isEmailNotVerifiedError,
} from "@/lib/format-api-error";
import { useTranslation } from "@/lib/i18n/useTranslation";
import { INVITATION_ROLES, getMembershipRoleLabel, type InvitationRole } from "@/lib/membership-role";
import type { Invitation, PlanLimitReachedDetail } from "@/lib/types";

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
  const [planLimitDetail, setPlanLimitDetail] = useState<PlanLimitReachedDetail | null>(null);

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
      const planLimit = getPlanLimitReachedDetail(err);
      if (planLimit) {
        setPlanLimitDetail(planLimit);
      } else {
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
      }
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
          <Input
            id="invite-email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            disabled={disabled}
            maxLength={EMAIL_MAX_LENGTH}
            placeholder="teammate@example.com"
            className="mt-1"
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
          <Select
            id="invite-role"
            value={role}
            onChange={(e) => setRole(e.target.value as InvitationRole)}
            disabled={disabled}
            className="mt-1 sm:w-40"
          >
            {INVITATION_ROLES.map((r) => (
              <option key={r} value={r}>
                {getMembershipRoleLabel(t, r)}
              </option>
            ))}
          </Select>
        </div>

        <Button type="submit" disabled={disabled}>
          {isSubmitting ? t("common.saving") : t("team.inviteButton")}
        </Button>
      </form>

      <PlanLimitReachedDialog detail={planLimitDetail} onClose={() => setPlanLimitDetail(null)} />
    </section>
  );
}
