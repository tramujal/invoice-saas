"use client";

import { FormEvent, useEffect, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { useToast } from "@/components/ui/toast";
import { apiFetch, orgPath } from "@/lib/api";
import { formatApiError, isEmailNotVerifiedError } from "@/lib/format-api-error";
import { useTranslation } from "@/lib/i18n/useTranslation";
import type { WebhookEndpointCreated, WebhookEventCatalogEntry } from "@/lib/types";
import {
  WEBHOOK_WILDCARD_EVENT,
  getWebhookEventDomainLabel,
  getWebhookEventLabel,
  groupEventsByDomain,
} from "@/lib/webhook-events";

const DESCRIPTION_MAX_LENGTH = 500;

type CreateWebhookEndpointFormProps = {
  onCreated: (created: WebhookEndpointCreated) => void;
};

export function CreateWebhookEndpointForm({ onCreated }: CreateWebhookEndpointFormProps) {
  const toast = useToast();
  const { t } = useTranslation();

  const [catalog, setCatalog] = useState<WebhookEventCatalogEntry[]>([]);
  const [url, setUrl] = useState("");
  const [description, setDescription] = useState("");
  const [allEvents, setAllEvents] = useState(false);
  const [events, setEvents] = useState<Set<string>>(new Set());
  const [urlError, setUrlError] = useState<string | null>(null);
  const [eventsError, setEventsError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    apiFetch<WebhookEventCatalogEntry[]>(orgPath("webhooks/event-types"))
      .then((rows) => {
        if (!cancelled) setCatalog(rows);
      })
      .catch(() => {
        // The create form still works with an empty catalog (just no
        // checkboxes render) -- a transient failure here shouldn't block
        // an otherwise-working page.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  function toggleEvent(eventType: string) {
    setEvents((prev) => {
      const next = new Set(prev);
      if (next.has(eventType)) next.delete(eventType);
      else next.add(eventType);
      return next;
    });
  }

  function resetForm() {
    setUrl("");
    setDescription("");
    setAllEvents(false);
    setEvents(new Set());
    setUrlError(null);
    setEventsError(null);
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();

    const trimmedUrl = url.trim();
    let hasError = false;
    if (!trimmedUrl || !/^https?:\/\//.test(trimmedUrl)) {
      setUrlError(t("webhooks.errorUrlRequired"));
      hasError = true;
    } else {
      setUrlError(null);
    }
    if (!allEvents && events.size === 0) {
      setEventsError(t("webhooks.errorEventsRequired"));
      hasError = true;
    } else {
      setEventsError(null);
    }
    if (hasError) return;

    const loadingId = toast.loading(t("webhooks.toastCreating"));
    setIsSubmitting(true);
    try {
      const created = await apiFetch<WebhookEndpointCreated>(orgPath("webhooks"), {
        method: "POST",
        body: JSON.stringify({
          url: trimmedUrl,
          description: description.trim(),
          subscribed_events: allEvents ? [WEBHOOK_WILDCARD_EVENT] : Array.from(events),
        }),
      });
      toast.dismiss(loadingId);
      toast.success(t("webhooks.toastCreated"));
      resetForm();
      onCreated(created);
    } catch (err) {
      toast.dismiss(loadingId);
      toast.error(
        isEmailNotVerifiedError(err) ? t("errors.emailNotVerified") : formatApiError(err, t("webhooks.toastCreateError"))
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  const disabled = isSubmitting;
  const groups = groupEventsByDomain(catalog);

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-6">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">{t("webhooks.createTitle")}</h2>
      <p className="mt-1 text-sm text-slate-500">{t("webhooks.createSubtitle")}</p>

      <form onSubmit={(e) => void handleSubmit(e)} className="mt-4 space-y-4" noValidate>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="sm:col-span-2">
            <label htmlFor="webhook-url" className="text-sm font-medium text-slate-700">
              {t("webhooks.urlLabel")} <span className="text-red-600">*</span>
            </label>
            <Input
              id="webhook-url"
              type="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              disabled={disabled}
              placeholder="https://example.com/webhooks/invoicing"
              className="mt-1"
              aria-invalid={Boolean(urlError)}
              aria-describedby={urlError ? "webhook-url-err" : undefined}
            />
            {urlError ? (
              <p id="webhook-url-err" className="mt-1 text-xs text-red-600" role="alert">
                {urlError}
              </p>
            ) : (
              <p className="mt-1 text-xs text-slate-500">{t("webhooks.urlHelp")}</p>
            )}
          </div>

          <div className="sm:col-span-2">
            <label htmlFor="webhook-description" className="text-sm font-medium text-slate-700">
              {t("webhooks.descriptionLabel")}
            </label>
            <Input
              id="webhook-description"
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              disabled={disabled}
              maxLength={DESCRIPTION_MAX_LENGTH}
              placeholder={t("webhooks.descriptionPlaceholder")}
              className="mt-1"
            />
          </div>
        </div>

        <fieldset>
          <legend className="text-sm font-medium text-slate-700">
            {t("webhooks.eventsLabel")} <span className="text-red-600">*</span>
          </legend>

          <label className="mt-2 flex items-center gap-2 text-sm font-medium text-slate-800">
            <input
              type="checkbox"
              checked={allEvents}
              onChange={(e) => setAllEvents(e.target.checked)}
              disabled={disabled}
              className="h-4 w-4 rounded border-slate-300 text-slate-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-400"
            />
            {t("webhooks.allEventsLabel")}
          </label>

          <div className={`mt-3 space-y-3 ${allEvents ? "opacity-50" : ""}`}>
            {groups.map((group) => (
              <div key={group.domain}>
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                  {getWebhookEventDomainLabel(t, group.domain)}
                </p>
                <div className="mt-1.5 grid grid-cols-1 gap-2 sm:grid-cols-3">
                  {group.events.map((entry) => (
                    <label key={entry.event_type} className="flex items-center gap-2 text-sm text-slate-700">
                      <input
                        type="checkbox"
                        checked={events.has(entry.event_type)}
                        onChange={() => toggleEvent(entry.event_type)}
                        disabled={disabled || allEvents}
                        className="h-4 w-4 rounded border-slate-300 text-slate-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-400"
                      />
                      {getWebhookEventLabel(t, entry.event_type)}
                    </label>
                  ))}
                </div>
              </div>
            ))}
          </div>

          {eventsError ? (
            <p className="mt-1 text-xs text-red-600" role="alert">
              {eventsError}
            </p>
          ) : null}
        </fieldset>

        <div className="flex justify-end pt-1">
          <Button type="submit" disabled={disabled}>
            {isSubmitting ? t("common.saving") : t("webhooks.createButton")}
          </Button>
        </div>
      </form>
    </section>
  );
}
