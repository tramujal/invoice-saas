"use client";

import { useCallback, useEffect, useState } from "react";

import { SettingsSubNav } from "@/components/settings/SettingsSubNav";
import { InviteMemberForm } from "@/components/team/InviteMemberForm";
import {
  RowActionsMenu,
  STICKY_ACTIONS_TD_CLASS,
  STICKY_ACTIONS_TH_CLASS,
} from "@/components/ui/RowActionsMenu";
import { useToast } from "@/components/ui/toast";
import { getUserEmail } from "@/lib/auth-storage";
import { ApiError, apiFetch, orgPath } from "@/lib/api";
import { formatApiError, getApiErrorCode } from "@/lib/format-api-error";
import { useTranslation } from "@/lib/i18n/useTranslation";
import type { TranslateFn } from "@/lib/i18n/useTranslation";
import {
  INVITATION_ROLES,
  MEMBERSHIP_ROLE_BADGE_CLASS,
  getMembershipRoleLabel,
  type InvitationRole,
} from "@/lib/membership-role";
import { hasPermission } from "@/lib/permissions";
import type { Invitation, Member, PaginatedInvitations, PaginatedMembers } from "@/lib/types";

// Translated at render time, not inside the callbacks below, since
// useTranslation()'s t is not identity-stable (see dashboard/customers
// pages for the same pattern).
const GENERIC_LOAD_ERROR = "__generic_load_error__";

function statusLabel(t: TranslateFn, status: Member["status"]): string {
  return status === "active" ? t("team.statusActive") : t("team.statusRemoved");
}

/** Whether this role can be set through the ordinary role-change select --
 * i.e. it's one of INVITATION_ROLES. Generalizes the old `role === "owner"`
 * special case: any role outside the assignable set (today just "owner",
 * but this stays correct for any future non-assignable role too) needs a
 * disabled placeholder option instead of a selectable value. */
function isAssignableRole(role: Member["role"]): role is InvitationRole {
  return (INVITATION_ROLES as readonly string[]).includes(role);
}

function roleChangeErrorMessage(t: TranslateFn, err: unknown): string {
  const code = getApiErrorCode(err);
  if (code === "owner_action_required") return t("team.errorOwnerActionRequired");
  if (code === "cannot_remove_last_owner") return t("team.errorCannotRemoveLastOwner");
  if (code === "confirmation_required") return t("team.errorConfirmationRequired");
  if (code === "member_already_removed") return t("team.errorMemberAlreadyRemoved");
  return formatApiError(err, t("team.toastActionError"));
}

export default function TeamPage() {
  const toast = useToast();
  const { t } = useTranslation();

  const [userEmail, setUserEmail] = useState<string | null>(null);
  useEffect(() => {
    setUserEmail(getUserEmail());
  }, []);

  const [members, setMembers] = useState<Member[] | null>(null);
  const [invitations, setInvitations] = useState<Invitation[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const self = members?.find((m) => m.user_email === userEmail) ?? null;
  // Gated on the caller's own permission set (see lib/permissions.ts), not
  // a role-name check -- a future custom role granted these permissions
  // shows the right controls automatically, with no change here.
  const canManageMembers = hasPermission(self, "members.manage");
  const canGrantOwnership = hasPermission(self, "organization.manage");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const membersResponse = await apiFetch<PaginatedMembers>(orgPath("members"));
      setMembers(membersResponse.items);

      const selfRow = membersResponse.items.find((m) => m.user_email === getUserEmail());
      if (hasPermission(selfRow, "members.manage")) {
        const invitationsResponse = await apiFetch<PaginatedInvitations>(orgPath("invitations"));
        setInvitations(invitationsResponse.items);
      } else {
        setInvitations(null);
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : GENERIC_LOAD_ERROR);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleRoleChange(member: Member, newRole: InvitationRole) {
    if (newRole === member.role) return;
    if (!window.confirm(t("team.confirmRoleChange", { email: member.user_email, role: getMembershipRoleLabel(t, newRole) }))) {
      return;
    }
    setBusyId(member.id);
    try {
      await apiFetch<Member>(orgPath(`members/${member.id}`), {
        method: "PATCH",
        body: JSON.stringify({ role: newRole }),
      });
      toast.success(t("team.toastRoleChanged"));
      await load();
    } catch (err) {
      toast.error(roleChangeErrorMessage(t, err));
    } finally {
      setBusyId(null);
    }
  }

  async function handleRemove(member: Member) {
    if (!window.confirm(t("team.confirmRemove", { email: member.user_email }))) return;
    setBusyId(member.id);
    try {
      await apiFetch<Member>(orgPath(`members/${member.id}/remove`), { method: "POST" });
      toast.success(t("team.toastRemoved"));
      await load();
    } catch (err) {
      toast.error(roleChangeErrorMessage(t, err));
    } finally {
      setBusyId(null);
    }
  }

  async function handleGrantOwnership(member: Member) {
    if (!window.confirm(t("team.confirmGrantOwnership", { email: member.user_email }))) return;
    setBusyId(member.id);
    try {
      await apiFetch<Member>(orgPath(`members/${member.id}/grant-ownership`), {
        method: "POST",
        body: JSON.stringify({ confirm: true }),
      });
      toast.success(t("team.toastOwnershipGranted"));
      await load();
    } catch (err) {
      toast.error(roleChangeErrorMessage(t, err));
    } finally {
      setBusyId(null);
    }
  }

  async function handleResendInvitation(invitation: Invitation) {
    setBusyId(invitation.id);
    try {
      await apiFetch<Invitation>(orgPath(`invitations/${invitation.id}/resend`), { method: "POST" });
      toast.success(t("team.toastInvitationResent"));
      await load();
    } catch (err) {
      toast.error(formatApiError(err, t("team.toastActionError")));
    } finally {
      setBusyId(null);
    }
  }

  async function handleCancelInvitation(invitation: Invitation) {
    if (!window.confirm(t("team.confirmCancelInvitation", { email: invitation.email }))) return;
    setBusyId(invitation.id);
    try {
      await apiFetch(orgPath(`invitations/${invitation.id}`), { method: "DELETE", parseJson: false });
      toast.success(t("team.toastInvitationCancelled"));
      await load();
    } catch (err) {
      toast.error(formatApiError(err, t("team.toastActionError")));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">{t("team.title")}</h1>
        <p className="mt-1 text-sm text-slate-500">{t("team.subtitle")}</p>
      </header>

      <SettingsSubNav />

      {error ? (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800" role="alert">
          {error === GENERIC_LOAD_ERROR ? t("team.loadError") : error}
        </div>
      ) : null}

      {canManageMembers ? <InviteMemberForm onInvited={load} /> : null}

      <section className="rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="border-b border-slate-100 p-4 sm:p-6">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
            {t("team.membersTitle")}
          </h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-slate-100 text-xs font-medium uppercase tracking-wide text-slate-500">
                <th className="px-4 py-3 sm:px-6">{t("common.email")}</th>
                <th className="px-4 py-3">{t("team.roleLabel")}</th>
                <th className="hidden px-4 py-3 sm:table-cell">{t("team.statusLabel")}</th>
                <th className="hidden px-4 py-3 md:table-cell">{t("team.joinedLabel")}</th>
                {canManageMembers ? (
                  <th className={STICKY_ACTIONS_TH_CLASS}>
                    <span className="sr-only">{t("team.colActions")}</span>
                  </th>
                ) : null}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={5} className="px-4 py-6 text-center text-sm text-slate-400 sm:px-6">
                    {t("team.loading")}
                  </td>
                </tr>
              ) : !members || members.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-4 py-6 text-center text-sm text-slate-400 sm:px-6">
                    {t("team.noMembers")}
                  </td>
                </tr>
              ) : (
                members.map((member) => {
                  const isSelf = member.user_email === userEmail;
                  const rowBusy = busyId === member.id;
                  return (
                    <tr key={member.id} className="group border-b border-slate-50 last:border-0 hover:bg-slate-50/80">
                      <td className="max-w-[180px] truncate px-4 py-3 sm:px-6" title={member.user_email}>
                        <span className="font-medium text-slate-900">{member.user_email}</span>
                        {isSelf ? (
                          <span className="ml-2 text-xs text-slate-400">{t("team.youLabel")}</span>
                        ) : null}
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ring-1 ring-inset ${MEMBERSHIP_ROLE_BADGE_CLASS[member.role]}`}
                        >
                          {getMembershipRoleLabel(t, member.role)}
                        </span>
                      </td>
                      <td className="hidden px-4 py-3 text-slate-600 sm:table-cell">{statusLabel(t, member.status)}</td>
                      <td className="hidden px-4 py-3 text-slate-600 md:table-cell">
                        {new Date(member.accepted_at).toLocaleDateString()}
                      </td>
                      {canManageMembers ? (
                        <td className={STICKY_ACTIONS_TD_CLASS}>
                          <div className="flex items-center justify-end gap-2">
                            <label htmlFor={`role-select-${member.id}`} className="sr-only">
                              {t("team.changeRoleLabel", { email: member.user_email })}
                            </label>
                            <select
                              id={`role-select-${member.id}`}
                              value={isAssignableRole(member.role) ? member.role : ""}
                              onChange={(e) => void handleRoleChange(member, e.target.value as InvitationRole)}
                              disabled={rowBusy}
                              className="rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-xs outline-none ring-slate-400 focus:ring-2 disabled:opacity-60"
                            >
                              {!isAssignableRole(member.role) ? (
                                <option value="" disabled>
                                  {getMembershipRoleLabel(t, member.role)}
                                </option>
                              ) : null}
                              {INVITATION_ROLES.map((r) => (
                                <option key={r} value={r}>
                                  {getMembershipRoleLabel(t, r)}
                                </option>
                              ))}
                            </select>
                            <RowActionsMenu label={t("common.moreActions")}>
                              {canGrantOwnership && !hasPermission(member, "organization.manage") ? (
                                <RowActionsMenu.Item
                                  onSelect={() => void handleGrantOwnership(member)}
                                  disabled={rowBusy}
                                >
                                  {t("team.grantOwnershipButton")}
                                </RowActionsMenu.Item>
                              ) : null}
                              <RowActionsMenu.Item
                                destructive
                                onSelect={() => void handleRemove(member)}
                                disabled={rowBusy}
                              >
                                {t("team.removeButton")}
                              </RowActionsMenu.Item>
                            </RowActionsMenu>
                          </div>
                        </td>
                      ) : null}
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </section>

      {canManageMembers ? (
        <section className="rounded-2xl border border-slate-200 bg-white shadow-sm">
          <div className="border-b border-slate-100 p-4 sm:p-6">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
              {t("team.pendingInvitationsTitle")}
            </h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-slate-100 text-xs font-medium uppercase tracking-wide text-slate-500">
                  <th className="px-4 py-3 sm:px-6">{t("common.email")}</th>
                  <th className="px-4 py-3">{t("team.roleLabel")}</th>
                  <th className="hidden px-4 py-3 sm:table-cell">{t("team.invitedByLabel")}</th>
                  <th className="hidden px-4 py-3 md:table-cell">{t("team.expiresLabel")}</th>
                  <th className={STICKY_ACTIONS_TH_CLASS}>
                    <span className="sr-only">{t("team.colActions")}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {!invitations || invitations.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="px-4 py-6 text-center text-sm text-slate-400 sm:px-6">
                      {t("team.noPendingInvitations")}
                    </td>
                  </tr>
                ) : (
                  invitations.map((invitation) => {
                    const rowBusy = busyId === invitation.id;
                    return (
                      <tr
                        key={invitation.id}
                        className="group border-b border-slate-50 last:border-0 hover:bg-slate-50/80"
                      >
                        <td
                          className="max-w-[180px] truncate px-4 py-3 font-medium text-slate-900 sm:px-6"
                          title={invitation.email}
                        >
                          {invitation.email}
                        </td>
                        <td className="px-4 py-3">
                          <span
                            className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ring-1 ring-inset ${MEMBERSHIP_ROLE_BADGE_CLASS[invitation.role]}`}
                          >
                            {getMembershipRoleLabel(t, invitation.role)}
                          </span>
                        </td>
                        <td className="hidden px-4 py-3 text-slate-600 sm:table-cell">{invitation.created_by_email ?? "—"}</td>
                        <td className="hidden px-4 py-3 text-slate-600 md:table-cell">
                          {new Date(invitation.expires_at).toLocaleDateString()}
                        </td>
                        <td className={STICKY_ACTIONS_TD_CLASS}>
                          <RowActionsMenu label={t("common.moreActions")}>
                            <RowActionsMenu.Item
                              onSelect={() => void handleResendInvitation(invitation)}
                              disabled={rowBusy}
                            >
                              {t("team.resendButton")}
                            </RowActionsMenu.Item>
                            <RowActionsMenu.Item
                              destructive
                              onSelect={() => void handleCancelInvitation(invitation)}
                              disabled={rowBusy}
                            >
                              {t("team.cancelButton")}
                            </RowActionsMenu.Item>
                          </RowActionsMenu>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}
    </div>
  );
}
