import type { TranslateFn } from "@/lib/i18n/useTranslation";

export const MEMBERSHIP_ROLES = ["owner", "admin", "member", "viewer"] as const;

export type MembershipRole = (typeof MEMBERSHIP_ROLES)[number];

/** Roles an invitation (or an ordinary role-change) may assign -- never
 * "owner", which can only be granted through the dedicated
 * grant-ownership action. Mirrors app.membership_role.InvitationRole. */
export const INVITATION_ROLES = ["admin", "member", "viewer"] as const;

export type InvitationRole = (typeof INVITATION_ROLES)[number];

export function isMembershipRole(value: string): value is MembershipRole {
  return (MEMBERSHIP_ROLES as readonly string[]).includes(value);
}

/** Same hook-free convention as lib/quote-status.ts's getQuoteStatusLabel. */
export function getMembershipRoleLabel(t: TranslateFn, role: MembershipRole | InvitationRole): string {
  return t(`membershipRole.${role}`);
}

export const MEMBERSHIP_ROLE_BADGE_CLASS: Record<MembershipRole, string> = {
  owner: "bg-violet-100 text-violet-900 ring-violet-200/80",
  admin: "bg-sky-100 text-sky-900 ring-sky-200/80",
  member: "bg-emerald-100 text-emerald-900 ring-emerald-200/80",
  viewer: "bg-slate-100 text-slate-700 ring-slate-200/80",
};

export const MEMBERSHIP_STATUSES = ["active", "removed"] as const;

export type MembershipStatus = (typeof MEMBERSHIP_STATUSES)[number];
