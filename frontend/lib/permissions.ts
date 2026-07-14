/**
 * Mirrors app.permissions.Permission (backend) -- the single source of
 * truth for what each role can do lives server-side; the frontend never
 * re-derives it from a role name. Every Member row the backend returns
 * carries its own `permissions: string[]` (see app.models.OrganizationMember
 * .permissions / app.schemas.MemberResponse), computed there from
 * ROLE_PERMISSIONS. UI gating should always go through hasPermission()
 * below, never a `member.role === "owner"` check -- that's what lets a
 * future custom role (Sales, Accountant, Support, Billing...) show the
 * right buttons with zero frontend changes.
 */
export type Permission =
  | "organization.manage"
  | "members.manage"
  | "settings.manage"
  | "billing.manage"
  | "customer.read"
  | "customer.write"
  | "product.read"
  | "product.write"
  | "invoice.read"
  | "invoice.create"
  | "invoice.edit"
  | "invoice.send"
  | "quote.read"
  | "quote.create"
  | "quote.edit"
  | "quote.send"
  | "quote.convert"
  | "assistant.chat"
  | "assistant.execute"
  | "dashboard.view"
  | "insights.view";

export function hasPermission(
  entity: { permissions: string[] } | null | undefined,
  permission: Permission
): boolean {
  return Boolean(entity?.permissions.includes(permission));
}
