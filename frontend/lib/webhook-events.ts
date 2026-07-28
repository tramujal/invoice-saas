import type { TranslateFn } from "@/lib/i18n/useTranslation";
import { WEBHOOK_WILDCARD_EVENT, type WebhookEventCatalogEntry } from "@/lib/types";

export { WEBHOOK_WILDCARD_EVENT };

/** One i18n key per event type, keyed by the exact wire value
 * (app.webhook_event_type.WebhookEventType) -- same convention as
 * lib/api-key-permissions.ts's getApiKeyPermissionLabel. */
export function getWebhookEventLabel(t: TranslateFn, eventType: string): string {
  return t(`webhooks.event.${eventType.replace(".", "_")}`);
}

export function getWebhookEventDomainLabel(t: TranslateFn, domain: string): string {
  return t(`webhooks.eventDomain.${domain}`);
}

export type WebhookEventGroup = {
  domain: string;
  events: WebhookEventCatalogEntry[];
};

/** Groups the flat catalog (as returned by GET .../webhooks/event-types)
 * into one section per domain, in first-seen order -- the API's own
 * enum declaration order, so the UI's grouping never needs its own
 * separate ordering rule. */
export function groupEventsByDomain(entries: WebhookEventCatalogEntry[]): WebhookEventGroup[] {
  const groups: WebhookEventGroup[] = [];
  const byDomain = new Map<string, WebhookEventGroup>();
  for (const entry of entries) {
    let group = byDomain.get(entry.domain);
    if (!group) {
      group = { domain: entry.domain, events: [] };
      byDomain.set(entry.domain, group);
      groups.push(group);
    }
    group.events.push(entry);
  }
  return groups;
}
