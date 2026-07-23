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

/** Mirrors app.role_hierarchy exactly -- viewer < member < admin < owner.
 * The backend is still the source of truth (every action here is re-
 * checked server-side regardless), but the UI shouldn't offer a control
 * that's guaranteed to come back 403: an admin viewing another admin's
 * row, or a role option at or above the actor's own rank, is hidden
 * rather than shown-then-rejected. */
const ROLE_RANK: Record<MembershipRole, number> = { viewer: 0, member: 1, admin: 2, owner: 3 };

/** Whether actorRole may modify/remove an *other* member currently
 * holding targetRole -- never call this for the actor's own row (self-
 * modification is exempt from this rule; the backend allows it subject
 * only to the last-owner invariant, and the UI already renders self
 * rows using the "you" label rather than hiding them here). */
export function canManageMember(actorRole: MembershipRole, targetRole: MembershipRole): boolean {
  if (actorRole === "owner" && targetRole === "owner") return true;
  return ROLE_RANK[actorRole] > ROLE_RANK[targetRole];
}

/** Every InvitationRole actorRole is senior enough to grant -- admin gets
 * [viewer, member], owner gets [viewer, member, admin]. */
export function assignableRolesFor(actorRole: MembershipRole): InvitationRole[] {
  return INVITATION_ROLES.filter((role) => ROLE_RANK[actorRole] > ROLE_RANK[role]);
}
