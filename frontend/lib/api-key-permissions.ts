import type { TranslateFn } from "@/lib/i18n/useTranslation";
import { API_KEY_PERMISSIONS, type ApiKeyPermission } from "@/lib/types";

export { API_KEY_PERMISSIONS };
export type { ApiKeyPermission };

/** Same hook-free convention as lib/membership-role.ts's
 * getMembershipRoleLabel -- one i18n key per permission, keyed by the
 * exact wire value (app.api_key_permissions.ApiKeyPermission). */
export function getApiKeyPermissionLabel(t: TranslateFn, permission: ApiKeyPermission): string {
  return t(`apiKeys.permission.${permission.replace(".", "_")}`);
}
